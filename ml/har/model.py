# /*---------------------------------------------------------------------------------------------
#  * Copyright (c) 2022 STMicroelectronics.
#  * All rights reserved.
#  *
#  * This software is licensed under terms that can be found in the LICENSE file in
#  * the root directory of this software component.
#  * If no LICENSE file comes with this software, it is provided AS-IS.
#  *--------------------------------------------------------------------------------------------*/
# Adapted from stm32ai-modelzoo-services
#   human_activity_recognition/tf/src/models/ign.py  (license: SLA0044)
# Changes: no global seed side effect at import; default input is 104 x 6 (accel + gyro).
"""ST-IGN: small CNN for human activity recognition (Ignatov 2018, ST variant).

Input layout is channels-last ``(time, axes, 1)``. The first Conv2D has a
(16, 1) kernel, so it convolves along time and shares the same filters across
every axis -- widening from 3 to 6 axes needs no architecture change.
"""
import tensorflow as tf
from tensorflow.keras import layers


def get_ign(input_shape: tuple[int, int, int] = (104, 6, 1),
            num_classes: int = 5,
            dropout: float = 0.5) -> tf.keras.Model:
    inputs = layers.Input(shape=input_shape)
    x = layers.Conv2D(24, kernel_size=(16, 1), strides=(1, 1))(inputs)
    x = layers.Activation("relu")(x)
    x = layers.MaxPooling2D(pool_size=(3, 1))(x)
    x = layers.Flatten()(x)
    x = layers.Dense(12)(x)
    if dropout:
        x = layers.Dropout(dropout)(x)
    outputs = layers.Dense(num_classes, activation="softmax")(x)
    return tf.keras.Model(inputs=inputs, outputs=outputs, name="st_ign")
