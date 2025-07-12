import logging
import math
import os
import time

from kubernetes import config, client

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Kubernetes deployment details for the image classification service
DEPLOYMENT_NAME = "image-classifier"
NAMESPACE = "default"
MONITOR_URL = "http://monitor:9000/stats"
LATENCY_THRESHOLD_S = 0.33
MIN_REPLICAS = 1
MAX_REPLICAS = 8
POLL_INTERVAL_S = 10
SCALE_UP_FACTOR = 1.2
SCALE_DOWN_STEP = 1

def get_p99_latency() -> float | None:
    """
    Fetches the 99th percentile latency from the monitor service.

    Returns:
        The p99 latency in seconds, or None if fetching fails.
    """
    try:
        import requests
        response = requests.get(MONITOR_URL, timeout=10)
        response.raise_for_status()
        stats = response.json()
        print(stats, response.status_code, stats.get("p99_latency"))
        return stats.get("p99_latency")
    except requests.exceptions.RequestException as e:
        logging.error(f"Could not fetch latency from monitor: {e}")
        return None

def get_current_replicas(apps_v1_api: client.AppsV1Api) -> int:
    """
    Gets the current number of replicas for the deployment.

    Args:
        apps_v1_api: An initialized Kubernetes AppsV1Api client.

    Returns:
        The current number of running replicas.
    """
    try:
        deployment = apps_v1_api.read_namespaced_deployment(DEPLOYMENT_NAME, NAMESPACE)
        return deployment.spec.replicas
    except client.ApiException as e:
        logging.error(f"Could not read deployment details: {e}")
        return -1

def scale_deployment(apps_v1_api: client.AppsV1Api, new_replica_count: int):
    """
    Scales the Kubernetes deployment to a new number of replicas.

    Args:
        apps_v1_api: An initialized Kubernetes AppsV1Api client.
        new_replica_count: The desired number of replicas.
    """
    new_replica_count = max(MIN_REPLICAS, min(MAX_REPLICAS, new_replica_count))
    body = {"spec": {"replicas": new_replica_count}}
    try:
        apps_v1_api.patch_namespaced_deployment_scale(
            name=DEPLOYMENT_NAME,
            namespace=NAMESPACE,
            body=body
        )
        logging.info(f"Successfully scaled deployment '{DEPLOYMENT_NAME}' to {new_replica_count} replicas.")
    except client.ApiException as e:
        logging.error(f"Could not scale deployment: {e}")

def main():
    """
    The main autoscaling loop.
    
    This function continuously polls the monitor for latency metrics and makes
    scaling decisions based on the configured thresholds.
    """
    logging.info("Starting custom autoscaler...")
    
    # Load Kubernetes configuration. This will load from in-cluster service account
    # when run inside a pod, or from the local kubeconfig file otherwise.
    if os.getenv("KUBERNETES_SERVICE_HOST"):
        config.load_incluster_config()
    else:
        config.load_kube_config()
    apps_v1 = client.AppsV1Api()
    logging.info("Kubernetes client initialized.")

    while True:
        p99_latency = get_p99_latency()
        print(p99_latency, " - Latency")
        if p99_latency is None:
            logging.warning("Skipping scaling cycle, could not retrieve latency.")
            time.sleep(POLL_INTERVAL_S)
            continue
        logging.info(f"Current p99 latency is {p99_latency:.4f}s. Target is < {LATENCY_THRESHOLD_S}s.")
        current_replicas = get_current_replicas(apps_v1)
        if current_replicas == -1:
            logging.warning("Skipping scaling cycle, could not retrieve current replica count.")
            time.sleep(POLL_INTERVAL_S)
            continue
        logging.info(f"Current replica count is {current_replicas}.")

        # --- Scaling Logic ---
        print(f"{p99_latency > LATENCY_THRESHOLD_S}, {p99_latency}, {LATENCY_THRESHOLD_S}")
        if p99_latency > LATENCY_THRESHOLD_S:
            new_replicas = math.ceil(current_replicas * SCALE_UP_FACTOR)
            if new_replicas > current_replicas:
                logging.info(f"Latency threshold breached. Scaling up from {current_replicas} to {new_replicas} replicas.")
                scale_deployment(apps_v1, new_replicas)
            else:
                logging.info("Latency threshold breached, but scale-up calculation did not yield more replicas. Holding steady.")

        else:
            print(f"Scale Down, Current replicas: {current_replicas}, Min replicas: {MIN_REPLICAS}")
            if current_replicas > MIN_REPLICAS:
                new_replicas = current_replicas - SCALE_DOWN_STEP
                logging.info(f"Latency is within threshold. Scaling down from {current_replicas} to {new_replicas} replicas.")
                scale_deployment(apps_v1, new_replicas)
            else:
                logging.info("Latency is within threshold and at minimum replicas. Holding steady.")
        time.sleep(POLL_INTERVAL_S)

if __name__ == "__main__":
    main() 