from .conf_parser import ConfParser
import configparser

class GenericConfParser(ConfParser):
    def __init__(self, conf_spec: dict):
        super().__init__()
        self.conf_spec = conf_spec
        for key in self.conf_spec:
            setattr(self, key, None)

    def load_conf_file(self, conf_path):
        parser = configparser.ConfigParser()
        try:
            parser.read(conf_path)
            default_conf = parser["DEFAULT"]

            for key, caster in self.conf_spec.items():
                if key not in default_conf:
                    print("Missing key in configuration: {}".format(key))
                    continue
                try:
                    setattr(self, key, caster(default_conf[key]))
                except Exception as e:
                    print("Failed to parse {}: {} ({})".format(key, default_conf[key], e))

            for key, value in default_conf.items():
                if key not in self.conf_spec:
                    casted_value = self._auto_cast(value)
                    setattr(self, key, casted_value)

        except FileNotFoundError:
            print("switch config file does not exist: {}".format(conf_path))

    def _auto_cast(self, value: str):
        if value.isdigit():
            return int(value)
        try:
            return float(value)
        except ValueError:
            return value


class BaseSettingConfParser(GenericConfParser):
    def __init__(self):
        super().__init__({
            "user": str,
            "remote_perftest_path": str,
            "remote_perftest_trace_dir": str,
            "remote_log_dir": str,
        })


class TestSettingConfParser(GenericConfParser):
    def __init__(self):
        super().__init__({
            "AR": lambda v: v.lower() == "on",
            "SLOW_START": lambda v: v.lower() == "on",
            "workload": str,
            "avgload": float,
            "bandwidth": str,
            "test_time": int,
        })