import os
import getpass
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"
from huggingface_hub import snapshot_download

try:
    print("Downloading BAAI/bge-m3 sequentially without progress bars...")
    path = snapshot_download(
        repo_id='BAAI/bge-m3',
        ignore_patterns=['flax_model.msgpack', 'rust_model.ot', 'tf_model.h5'],
        max_workers=1
    )
    print(f"Downloaded to {path}")
except Exception as e:
    print(f"Failed: {e}")
