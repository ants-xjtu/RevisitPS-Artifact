from abc import ABC, abstractmethod
class ConfParser(ABC):
  def __init__(self, conf_path):
    self.conf_path = conf_path
    pass
  @abstractmethod
  def load_conf_file(self):
    pass