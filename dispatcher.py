import logging
import os
import random
import time
from contextlib import asynccontextmanager
import threading

import requests
from fastapi import FastAPI, Request
from kubernetes import client, config, watch

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# The name of the backend service we are dispatching to.
SERVICE_NAME = "image-classifier"
NAMESPACE = "default"
SERVICE_PORT = 5000
MONITOR_URL = "http://monitor:9000/record"

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    
    This context manager handles the startup and shutdown events of the application.
    On startup, it loads the Kubernetes configuration and starts a background
    thread to watch for pod updates.
    """
    logging.info("Dispatcher starting up...")
    # Load Kubernetes configuration based on the environment
    if os.getenv("KUBERNETES_SERVICE_HOST"):
        config.load_incluster_config()
    else:
        config.load_kube_config()
    # Start the pod IP watcher in a background thread
    threading.Thread(target=update_pod_ips_periodically, daemon=True).start()
    logging.info("Background thread for pod discovery started.")
    yield
    # This part runs on shutdown.
    logging.info("Dispatcher shutting down...")

app = FastAPI(lifespan=lifespan)

# A list to hold the IP addresses of the backend pods.
POD_IPS = []

def watch_for_pod_updates():
    """
    Watches the Kubernetes API for changes to pods matching our service label.
    
    This function runs in a background thread and keeps the global POD_IPS list
    up-to-date with the IP addresses of running and ready pods.
    """
    # Use a Kubernetes Watcher to get real-time updates on pod events.
    w = watch.Watch()
    # We watch for events on pods in our namespace that have the label 'app=image-classifier'.
    for event in w.stream(
        func=client.CoreV1Api().list_namespaced_pod,
        namespace=NAMESPACE,
        label_selector=f"app={SERVICE_NAME}",
        timeout_seconds=60  # Periodically timeout to refresh the watch
    ):
        pod = event["object"]
        pod_ip = pod.status.pod_ip
        # We only care about pods that have an IP address and are in the 'Running' phase.
        if pod_ip and pod.status.phase == "Running":
            if event["type"] == "ADDED" or event["type"] == "MODIFIED":
                if pod_ip not in POD_IPS:
                    logging.info(f"Adding pod {pod.metadata.name} with IP {pod_ip} to the pool.")
                    POD_IPS.append(pod_ip)
            elif event["type"] == "DELETED":
                if pod_ip in POD_IPS:
                    logging.info(f"Removing pod {pod.metadata.name} with IP {pod_ip} from the pool.")
                    POD_IPS.remove(pod_ip)

def update_pod_ips_periodically():
    """
    A wrapper function to run the Kubernetes watcher in a loop.
    
    This ensures that if the watch connection breaks or times out, a new
    one is established to maintain service discovery.
    """
    while True:
        try:
            watch_for_pod_updates()
        except Exception as e:
            logging.error(f"Error in Kubernetes watch stream: {e}. Retrying in 5 seconds...")
            POD_IPS.clear()
            time.sleep(5)


@app.post("/")
async def dispatch(request: Request):
    """
    The main dispatch endpoint.
    
    This function receives a request, forwards it to a randomly chosen
    backend pod, measures the latency, and reports it to the monitor.
    """
    start_time = time.time()
    if not POD_IPS:
        return {"error": "No backend pods available"}, 503

    # --- Round-Robin Load Balancing ---
    # Select a random pod from our list of available IPs.
    pod_ip = random.choice(POD_IPS)
    backend_url = f"http://{pod_ip}:{SERVICE_PORT}/predict"
    
    try:
        print(f"Dispatching request to backend pod at {backend_url}")
        # Forward the request content to the chosen backend pod.
        form = await request.form()
        image = form["image"]
        image_bytes = await image.read()
        files = {"image": (image.filename, image_bytes, image.content_type)}

        response = requests.post(backend_url, files=files, timeout=10)
        response.raise_for_status()

        # Calculate the end-to-end latency.
        latency = time.time() - start_time

        # Report the latency to the monitor service in a non-blocking way.
        try:
            print(f"Reported latency {latency:.3f}s to monitor at {MONITOR_URL}")
            requests.post(MONITOR_URL, json={"latency": latency}, timeout=1)
        except requests.exceptions.RequestException as e:
            logging.warning(f"Could not report latency to monitor: {e}")
            
        return response.json()

    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to dispatch request to {backend_url}: {e}")
        # If a pod fails, remove it from the list to avoid sending more
        # requests to it until the watcher verifies its status again.
        if pod_ip in POD_IPS:
            POD_IPS.remove(pod_ip)
        return {"error": f"Failed to connect to backend service: {e}"}, 500

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080) 