import requests
import time
import matplotlib.pyplot as plt
from kubernetes import client, config
import threading
from pathlib import Path

class LoadTester:
    def __init__(self, workload_file: str = "workload.txt"):
        scale_factor = 1
        self.service_url = self.get_dispatcher_url()
        print("Service URL", self.service_url)
        # Parse workload pattern from file (one integer per line)
        if Path(workload_file).exists():
            with open(workload_file) as f:
                workload_raw = [int(x) for x in f.read().strip().split()] or [1]
                # Scale down the workload based on system capacity
                self.workload = list(map(lambda r: int(r / scale_factor), workload_raw))
                print(f"Original workload peak: {max(workload_raw)} RPS")
                print(f"Scaled workload peak: {max(self.workload)} RPS (scale factor: {scale_factor})")
        else:
            self.workload = [1]
        self.results = []

    def get_dispatcher_url(self):
        try:
            # Try to load in-cluster config
            config.load_incluster_config()
            v1 = client.CoreV1Api()
            service = v1.read_namespaced_service("dispatcher", "default")
            print("Service", service.spec.type, service.spec.cluster_ip, service.spec.ports[0].port)
            if service.spec.type == "ClusterIP":
                return f"http://{service.spec.cluster_ip}:{service.spec.ports[0].port}"
            else:
                return f"http://{service.metadata.name}.{service.metadata.namespace}.svc.cluster.local:{service.spec.ports[0].port}"
        except Exception as e:
            print(f"Error getting service URL: {e}")
            return "http://localhost:8080"  # Fallback to localhost

    def send_request(self, image_path):
        with open(image_path, 'rb') as f:
            files = {'image': (Path(image_path).name, f, 'image/jpeg')}
            resp = requests.post(f"{self.service_url}/", files=files, timeout=10)
            return resp.status_code

    def run_test(self, image_path):
        for rps in self.workload:
            requests = []
            def worker():
                code = self.send_request(image_path)
                if code == 200:
                    requests.append(code)
            threads = []
            for _ in range(rps):
                t = threading.Thread(target=worker)
                t.start()
                threads.append(t)
                time.sleep(1.0 / max(rps,1))
            for t in threads:
                t.join()
            if requests:
                print(f"RPS {rps} | Successful requests: {len(requests)}")
                self.results.append(rps)

if __name__ == "__main__":
    tester = LoadTester()
    image_dir = Path("images")
    image_files = list(image_dir.glob("*.jpg")) 
    import random
    image_path = str(random.choice(image_files))  

    print(f"Starting load test with image: {image_path}")
    print(f"Using dispatcher URL: {tester.service_url}")
    tester.run_test(image_path)
