"""Human activity recognition (accelerometer + gyroscope) for the STM32 activity tracker."""
from .inference import HARClassifier, Prediction, board_to_model_units

__all__ = ["HARClassifier", "Prediction", "board_to_model_units"]
