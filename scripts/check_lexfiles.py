from datasets import load_dataset_builder
import os
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
builder = load_dataset_builder("lexlms/lex_files")
print("Description:", (builder.info.description or "")[:500])
print()
configs = builder.builder_configs
if isinstance(configs, dict):
    for name, cfg in configs.items():
        desc = (cfg.description or "")[:100]
        print(f"  {name}: {desc}")
print()
if builder.info.features:
    print("Features:", dict(builder.info.features))
if builder.info.splits:
    for name, split_info in builder.info.splits.items():
        print(f"Split {name}: {split_info.num_examples} examples")
