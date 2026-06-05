import json
import os

class Config:
    def __init__(self):
        self.config_dir = os.path.expanduser("~/.meet_translator")
        self.config_file = os.path.join(self.config_dir, "config.json")
        self.defaults = {
            "api_key": "",
            "output_device": 0,
            "input_device": -1,
            "source_language": "zh",
            "target_language": "en",
            "auto_start": False,
            "log_level": "INFO"
        }
        self._load()
    
    def _load(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r") as f:
                    data = json.load(f)
                    for key, value in data.items():
                        if key in self.defaults:
                            setattr(self, key, value)
            except Exception as e:
                print(f"Failed to load config: {e}")
        
        for key, value in self.defaults.items():
            if not hasattr(self, key):
                setattr(self, key, value)
    
    def save(self):
        os.makedirs(self.config_dir, exist_ok=True)
        data = {key: getattr(self, key) for key in self.defaults.keys()}
        with open(self.config_file, "w") as f:
            json.dump(data, f, indent=2)
    
    def __getattr__(self, name):
        if name in self.defaults:
            return self.defaults[name]
        raise AttributeError(f"'Config' object has no attribute '{name}'")