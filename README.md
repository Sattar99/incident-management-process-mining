# Irish Economy Data Platform: Incident Process Optimization Pipeline

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Project Status](https://img.shields.io/badge/Status-Analysis%20Complete-brightgreen.svg)](https://github.com/your-username/irish-economy-platform)
[![Python Version](https://img.shields.io/badge/Python-3.11.6-orange.svg)](https://www.python.org/downloads/release/python-3116/)

## Overview

This repository houses the end-to-end data pipeline built to automate the monitoring and optimization of the Irish Incident Management workflow. Instead of manually tracking spreadsheet data, this system pulls raw event logs, transforms them into a structured, time-sequenced process, and provides quantifiable Key Performance Indicators (KPIs) to drive business decisions.

**Goal:** Transform raw data into an actionable intelligence layer, proving the ability to move from **Data Analyst $\rightarrow$ Data Engineer $\rightarrow$ AI Analyst**.

## Architecture Diagram (Conceptual)

The pipeline follows a classic modern data stack pattern:

`Raw Data (CSV) $\xrightarrow{\text{ETL (Pandas/SQL)}} \text{Data Warehouse (PostgreSQL)} \xrightarrow{\text{Analytics (SQL/Python)}} \text{BI Visualization (Power BI)} \xrightarrow{\text{AI Layer (Agent)}} \text{Actionable Insight}$`

## Key Achievements

*   **Automated Ingestion:** Reads `Incident_Management_CSV.csv` using Python/Pandas.
*   **Persistence:** Loads and structures 242k+ events into a PostgreSQL database (`incident_events`).
*   **Process Sequencing:** Chronologically orders every event within each `Case ID` to map the true flow.
*   **Performance KPI Calculation:** Calculates **Total Cycle Time** and **Average Step Duration** per incident.
*   **Bottleneck Identification:** Pinpointed the most time-consuming events via SQL aggregation.
*   **AI Readiness:** The process is fully prepared for NLP/ML classification (e.g., classifying incoming tickets before they enter the flow).

## Technologies Used

*   **Core Language:** Python 3.11.6
*   **Data Handling:** Pandas
*   **Data Persistence:** PostgreSQL (via SQLAlchemy)
*   **Analytics Engine:** SQL
*   **Visualization Target:** Power BI
*   **Intelligence:** Hermes Agent (Future)

## How to Run This Project

1.  **Prerequisites:** Ensure PostgreSQL is running locally and accessible.
2.  **Clone Repository:** `git clone [Your-Repo-URL]`
3.  **Install Dependencies:** `pip install pandas sqlalchemy psycopg2-binary`
4.  **Configure DB:** Update the `DB_CONNECTION_STRING` in the main script to match your credentials.
5.  **Run ETL:** Execute the Python script (`etl_pipeline.py`).
6.  **Analyze:** Connect Power BI directly to the `incident_data` database and use the metrics in `RESULTS_AND_SUGGESTIONS.md` to guide dashboard design.
