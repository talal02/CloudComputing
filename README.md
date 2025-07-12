# Elastic ML Inference Demo on Minikube

This project shows a minimal yet **complete** example of an _elastic_ image-classification service on Kubernetes that automatically scales to keep the **99-th percentile latency below 0.33 s** (goal: < 0.5 s).

---

## 1. Architecture Diagram
```
[ Clients ] ──▶  Dispatcher (FastAPI) ──▶  Image-Service Pods (FastAPI + MobileNetV2)
            │                              ▲
            └─▶  Monitor  ◀──────── Autoscaler (python k8s-client)
```
* **dispatcher.py**
  * Round-robin (random) routes requests to one of the `image-service` pods and records end-to-end latency in the **Monitor**.
* **image_service.py**
  * FastAPI wrapper around **torchvision.MobileNetV2** pre-trained on ImageNet.
* **monitor.py**
  * Tiny FastAPI app that stores a rolling window of the last 1 000 latencies and serves `/stats` (JSON).
* **autoscaler.py**
  * Polls `/stats` every 10 s and patches the Kubernetes Deployment so that p99 < 0.33 s.  Scales up fast (×1.2) and scales down slowly (-1).
* **load_tester.py**
  * Simple thread-based load generator.  The file `workload.txt` defines one value per line (requests-per-second).

---

## 2. Quick-start on Minikube
1. Start a local cluster with CPU/Memory that can handle a few replicas:  
   ```bash
   minikube start --cpus 12 --memory 14g
   ```
2. Enable the registry addon (handy for loading local images):  
   ```bash
   minikube addons enable registry
   eval $(minikube -p minikube docker-env) # Point Docker-CLI to the in-cluster daemon.
   # OR Load Each Image Separately after building
   minikube image load demo/monitor:latest
   minikube image load demo/dispatcher:latest
   minikube image load demo/image-service:latest
   minikube image load demo/autoscaler:latest
   ```
3. Firstly, Build & tag all images **inside** Minikube's Docker daemon:
   ```bash
   docker build -t demo/image-service:latest -f Dockerfile.image_service .
   docker build -t demo/dispatcher:latest   -f Dockerfile.dispatcher   .
   docker build -t demo/monitor:latest      -f Dockerfile.monitor      .
   docker build -t demo/autoscaler:latest   -f Dockerfile.autoscaler   .
   ```
4. Deploy everything:
   ```bash
   kubectl apply -f k8s/
   ```
5. Port-forward the Dispatcher to your laptop:
   ```bash
   kubectl port-forward svc/dispatcher 8080:8080
   ```
6. Fire the load tester:
   ```bash
   python load_tester.py
   ```

---