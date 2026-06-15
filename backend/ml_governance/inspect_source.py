import mlflow
from mlflow.tracking import MlflowClient
import os

mlflow.set_tracking_uri("http://127.0.0.1:5000")
client = MlflowClient()
mv = client.get_model_version("synthetic_customer_classifier", "1")
print("mv.source:", mv.source)
print("Absolute path exists:", os.path.exists(mv.source))
# If it's relative, let's see where it is
print("Relative to CWD:", os.path.abspath(mv.source))
