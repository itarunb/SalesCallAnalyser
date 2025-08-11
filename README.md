# 📞 High-Ticket Sales Call Analyzer

This project is a powerful, serverless solution for automatically transcribing and analyzing sales call videos. It leverages Google Cloud Platform (GCP) services to create a hands-free pipeline that converts raw video recordings into actionable sales insights.

The system is designed for sales professionals, managers, and coaches who need to quickly review and improve their sales conversations without the time-consuming manual process of listening to every call.

## ✨ Features

* **Automated Transcription:** Automatically transcribes spoken dialogue from uploaded video files.

* **Speaker Diarization:** Identifies and labels up to two different speakers in the conversation (e.g., "Speaker 1" and "Speaker 2").

* **AI-Powered Analysis:** Uses the Gemini 2.5 Pro LLM to act as a virtual sales coach, analyzing the transcript for key sales principles and identifying flaws.

* **Serverless Architecture:** The entire pipeline runs on Google Cloud Functions, ensuring it's highly scalable, cost-effective (you only pay when it runs), and requires zero server management.

* **Secure & Scalable:** Files are securely stored in Google Cloud Storage, and the system can handle large numbers of concurrent video uploads without performance degradation.

* **Structured Output:** The raw transcription and the detailed AI analysis are saved as separate text files in a designated output bucket.

## ⚙️ Project Architecture

The project follows a classic event-driven serverless architecture on Google Cloud:

1. **Video Upload:** A user uploads a sales call video (e.g., a `.webm` or `.mp4` file) to a dedicated **Google Cloud Storage (GCS)** input bucket.

2. **Event Trigger:** The GCS file upload triggers a **2nd Generation Google Cloud Function** via an **Eventarc** trigger.

3. **Video Processing:** The Cloud Function performs the following steps:

   * Downloads the video file.

   * Uses `FFmpeg` to extract the audio track, converting it to a high-quality `.flac` format.

   * Uploads the extracted audio to an output GCS bucket.

4. **Transcription:** The function sends the audio file's GCS URI to the **Google Cloud Speech-to-Text API**.

5. **AI Analysis:** Once the transcription is complete, the function takes the transcribed text and constructs a detailed prompt for the **Gemini 2.5 Pro LLM**. This prompt includes a custom persona and a sales analysis framework.

6. **Output Generation:** The AI's analysis is saved as a structured text file in the output GCS bucket.

## 🚀 Getting Started

Follow these steps to set up and deploy the project in your own Google Cloud environment.

### Prerequisites

* A **Google Cloud Platform (GCP)** account with an active billing account.

* The **`gcloud` command-line tool** installed and configured on your local machine.

* A **Gemini API key**, obtained from [Google AI Studio](https://aistudio.google.com/app/apikey).

### 1. Enable Google Cloud APIs

In your GCP project, enable the following APIs:

* **Cloud Storage API**

* **Cloud Functions API**

* **Cloud Speech-to-Text API**

* **Generative Language API** (for Gemini)

### 2. Create Cloud Storage Buckets

Create two unique GCS buckets in the same region (e.g., `asia-south1`) as your function:

* **Input Bucket:** For uploading video files. (e.g., `salescallanalyzer_inputfiles`)

* **Output Bucket:** For storing audio and transcription results. (e.g., `salescallanalyzer_outputfiles`)

### 3. Grant IAM Permissions

The Cloud Function's default service accounts need specific permissions to interact with these services.

* **Eventarc Service Agent (`service-<YOUR_PROJECT_NUMBER>@gcp-sa-eventarc.iam.gserviceaccount.com`)**
  * Role: `Storage Object Viewer`

* **Cloud Storage Service Account (`service-<YOUR_PROJECT_NUMBER>@gs-project-accounts.iam.gserviceaccount.com`)**
  * Role: `Pub/Sub Publisher`

### 4. Prepare and Deploy the Cloud Function

1. Create a local directory for your project.

2. Create two files inside this directory:

   * `main.py`: Paste the Python script code.

   * `requirements.txt`: Add the necessary Python libraries with specific versions to avoid dependency conflicts:

     ```
     google-cloud-storage>=2.10.0
     google-cloud-speech>=2.24.0
     functions-framework>=3.5.0
     google-generativeai>=0.5.0
     
     
     ```

3. Deploy the function using the `gcloud CLI`. This command uses a buildpack to create the container image and securely sets environment variables.
