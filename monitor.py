from prometheus_client import start_http_server, Gauge, Histogram
import time
import psutil
import threading
import socket
from fastapi import FastAPI, Body, Request
from fastapi.responses import JSONResponse
from collections import deque
import statistics
import uvicorn
import logging
import numpy as np

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

cpu_usage = Gauge('cpu_usage_percent', 'CPU Usage in percent')
request_latency = Histogram('request_latency_seconds', 'Request latency in seconds')

# The maximum number of latency measurements to store in our rolling window.
MAX_LATENCIES = 1000

app = FastAPI(title="Latency Monitor")

# A deque (double-ended queue) is used to store the latency measurements.
LATENCIES = deque(maxlen=MAX_LATENCIES)

@app.post("/record")
async def record_latency(request: Request):
    """
    Receives a latency measurement from the dispatcher and adds it to the queue.
    
    Expects a JSON payload like: {"latency": 0.123}
    """
    data = await request.json()
    latency = data.get("latency")
    print(f"Received latency: {latency}")
    if latency is not None:
        LATENCIES.append(float(latency))
        return {"status": "ok"}
    return {"status": "error", "message": "Latency not provided"}, 400

@app.get("/stats")
def get_stats():
    """
    Calculates and returns statistics over the current window of latencies.
    
    This is the endpoint polled by the custom autoscaler.
    """
    if not LATENCIES:
        # If we have no data, return a default empty response.
        return {
            "p99_latency": 0.0,
            "p90_latency": 0.0,
            "p50_latency": 0.0,
            "average_latency": 0.0,
            "measurement_count": 0
        }
        
    # Use NumPy to efficiently calculate percentiles and average.
    latencies_array = np.array(LATENCIES)
    p99 = np.percentile(latencies_array, 99)
    p90 = np.percentile(latencies_array, 90)
    p50 = np.percentile(latencies_array, 50)
    avg = np.mean(latencies_array)
    
    logging.info(f"Serving stats: p99={p99:.4f}s over {len(LATENCIES)} measurements.")
    
    return {
        "p99_latency": p99,
        "p90_latency": p90,
        "p50_latency": p50,
        "average_latency": avg,
        "measurement_count": len(LATENCIES)
    }

def update_cpu_metrics():
    while True:
        try:
            cpu_usage.set(psutil.cpu_percent())
            time.sleep(1)
        except Exception as e:
            print(f"Error updating CPU metrics: {e}")

def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def start_monitoring(port=8000):
    # Check if port is available
    if is_port_in_use(port):
        print(f"Warning: Port {port} is already in use!")
        return

    # Start CPU monitoring in background
    threading.Thread(target=update_cpu_metrics, daemon=True).start()
    
    try:
        # Start Prometheus metrics server
        start_http_server(port, addr='0.0.0.0')  # Bind to all interfaces
        print(f"Monitoring server started on port {port}")
        print(f"Try accessing metrics at: http://localhost:{port}/metrics")
        
        # Keep the main thread alive
        while True:
            time.sleep(1)
    except Exception as e:
        print(f"Error starting monitoring server: {e}")

if __name__ == '__main__':
    # Run tiny server; in Kubernetes expose via ClusterIP
    uvicorn.run(app, host="0.0.0.0", port=9000) 
