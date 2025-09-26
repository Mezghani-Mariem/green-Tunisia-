🌍 Green Tunisia — Smart Multi-Compartment Waste Management

📌 Overview

Green Tunisia is a smart waste management system developed for Sfax, Tunisia. It combines:

IoT-enabled multi-compartment bins (Plastic, Metal, Paper, Organic, Bread, Glass).

A web application for real-time monitoring and route optimization.

An AI model (LSTM) to forecast bin fullness and schedule garbage truck trips efficiently.

ESP32 firmware to convert ultrasonic sensor data into fill-level percentages.

The project addresses key challenges such as overflowing bins, static collection schedules, high fuel consumption, and lack of real-time data.

🗂 Project Components
1. 📡 IoT Firmware (ESP32)

Reads distance using an ultrasonic sensor.

Converts distance measurements into bin fill percentage.

Sends the fill-level data  to the server.


2. 🌐 Web Application

Live dashboard with map of bins and fill levels.

Route optimization (Nearest Neighbor + 2-Opt).

Backend (Flask + DB) for data storage and API.

Operator interface + Driver PWA with collection checklist.

3. 🤖 AI Model

LSTM neural network for short-term fill-level forecasting.

Inputs: last 6h data (fill % history, time encoding, zone, waste type).

Outputs: next 6h predicted fill levels.

Trigger rule: dispatch a truck if predicted bins (≥80%) match truck capacity.

Metrics: MAE, RMSE, R², classification accuracy for ≥80% bins.
