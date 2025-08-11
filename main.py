# main.py
import functions_framework
from google.cloud import storage
from google.cloud import speech_v1p1beta1 as speech
import google.generativeai as genai # Import the Gemini API client
import os
import subprocess
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Google Cloud Storage client
storage_client = storage.Client()

@functions_framework.cloud_event
def transcribe_video_from_gcs(cloud_event):
    """
    Google Cloud Function to transcribe video files uploaded to a GCS bucket,
    and then analyze the transcription using a Gemini LLM.

    Args:
        cloud_event (dict): The Cloud Storage event data.
            Expected structure includes 'bucket' and 'name' (file path).
    """
    data = cloud_event.data
    bucket_name = data['bucket']
    file_name = data['name']
    mime_type = data['contentType']

    logger.info(f"Received upload event for file: {file_name} in bucket: {bucket_name}")
    logger.info(f"MIME type: {mime_type}")

    # --- Configuration ---
    INPUT_VIDEO_BUCKET = os.environ.get('INPUT_VIDEO_BUCKET', 'your-input-video-bucket')
    TRANSCRIPTION_OUTPUT_BUCKET = os.environ.get('TRANSCRIPTION_OUTPUT_BUCKET', 'your-transcription-output-bucket')
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY') # Get Gemini API Key from environment variables
    TEMP_DIR = '/tmp'

    if not GEMINI_API_KEY:
        logger.error("GEMINI_API_KEY environment variable not set. Cannot perform Gemini analysis.")
        raise ValueError("GEMINI_API_KEY is required.")

    # Ensure the event is for the correct input bucket
    if bucket_name != INPUT_VIDEO_BUCKET:
        logger.warning(f"Ignoring event from unexpected bucket: {bucket_name}. Expected: {INPUT_VIDEO_BUCKET}")
        return

    # Only process video files (you might want to refine this check)
    if not mime_type.startswith('video/'):
        logger.warning(f"Skipping non-video file: {file_name} (MIME type: {mime_type})")
        return

    # Construct local paths and GCS output paths
    base_file_name = os.path.splitext(os.path.basename(file_name))[0]
    local_video_path = os.path.join(TEMP_DIR, os.path.basename(file_name))
    local_audio_path = os.path.join(TEMP_DIR, f"{base_file_name}.flac")
    gcs_audio_path = f"audio/{base_file_name}.flac"
    gcs_transcript_path = f"transcripts/{base_file_name}.txt"
    gcs_analysis_path = f"analysis/{base_file_name}_analysis.txt" # New path for Gemini analysis

    try:
        # 1. Download the video file from GCS
        logger.info(f"Downloading {file_name} from gs://{bucket_name} to {local_video_path}")
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(file_name)
        blob.download_to_filename(local_video_path)
        logger.info(f"Successfully downloaded {file_name}. Local file size: {os.path.getsize(local_video_path)} bytes") # Added logging

        # 2. Extract audio from the video using FFmpeg
        ffmpeg_command = [
            'ffmpeg',
            '-i', local_video_path,
            '-vn',
            '-acodec', 'flac',
            '-ar', '16000',
            '-ac', '1',
            local_audio_path
        ]
        logger.info(f"Executing FFmpeg command: {' '.join(ffmpeg_command)}")
        try:
            ffmpeg_result = subprocess.run(ffmpeg_command, check=True, capture_output=True, text=True) # Capture stdout/stderr
            logger.info(f"FFmpeg stdout: {ffmpeg_result.stdout}")
            logger.info(f"FFmpeg stderr: {ffmpeg_result.stderr}")
            logger.info(f"Successfully extracted audio to {local_audio_path}. Local audio file size: {os.path.getsize(local_audio_path)} bytes") # Added logging
            if os.path.getsize(local_audio_path) == 0:
                logger.warning("FFmpeg extracted an empty audio file. This will result in no transcription.")
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg command failed: {e.stderr}")
            raise # Re-raise to stop execution if FFmpeg fails

        # 3. Upload the extracted audio to GCS
        output_bucket = storage_client.bucket(TRANSCRIPTION_OUTPUT_BUCKET)
        audio_blob = output_bucket.blob(gcs_audio_path)
        audio_blob.upload_from_filename(local_audio_path)
        logger.info(f"Uploaded extracted audio to gs://{TRANSCRIPTION_OUTPUT_BUCKET}/{gcs_audio_path}")

        # 4. Call the Google Cloud Speech-to-Text API
        speech_client = speech.SpeechClient()

        audio = speech.RecognitionAudio(uri=f"gs://{TRANSCRIPTION_OUTPUT_BUCKET}/{gcs_audio_path}")
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.FLAC,
            sample_rate_hertz=16000,
            language_code="en-IN",
            enable_automatic_punctuation=True,
            enable_speaker_diarization=True,
            diarization_config=speech.SpeakerDiarizationConfig(
                min_speaker_count=1,
                max_speaker_count=2,
            ),
            # model="video",
        )

        logger.info("Sending audio to Speech-to-Text API for transcription...")
        operation = speech_client.long_running_recognize(config=config, audio=audio)
        response = operation.result(timeout=600)

        # Added logging for Speech-to-Text response
        if not response.results:
            logger.warning("Speech-to-Text API returned no transcription results. This often means the audio was silent or unintelligible.")
        else:
            logger.info(f"Speech-to-Text API returned {len(response.results)} transcription results.")

        transcript_content = ""
        speaker_transcripts = {}
        for i, result in enumerate(response.results):
            logger.info(f"Processing Speech-to-Text result {i+1}: Alternative 0 confidence: {result.alternatives[0].confidence}")
            if result.alternatives[0].words: # Check if words are present for diarization
                for word_info in result.alternatives[0].words:
                    speaker_tag = word_info.speaker_tag
                    word = word_info.word
                    if speaker_tag not in speaker_transcripts:
                        speaker_transcripts[speaker_tag] = []
                    speaker_transcripts[speaker_tag].append(word)
            else:
                # If no words but a transcript, append directly (less common with diarization)
                transcript_content += result.alternatives[0].transcript + "\n"

        # If speaker_transcripts was populated, format it
        if speaker_transcripts:
            for speaker_tag in sorted(speaker_transcripts.keys()):
                transcript_content += f"Speaker {speaker_tag}: {' '.join(speaker_transcripts[speaker_tag])}\n"
        elif not transcript_content and response.results: # Fallback if diarization didn't yield words but there was a transcript
            logger.warning("Diarization did not yield word-level info, falling back to full transcript from alternatives.")
            for result in response.results:
                transcript_content += result.alternatives[0].transcript + "\n"


        logger.info("Transcription complete.")
        logger.info(f"Length of final transcript_content: {len(transcript_content)} characters.") # Added logging
        if len(transcript_content) == 0:
            logger.error("Final transcript_content is empty. Gemini will receive an empty transcript.")
        else:
            logger.info(f"Partial Transcript (first 200 chars): {transcript_content[:200]}...")

        # 5. Save the transcription to GCS
        transcript_blob = output_bucket.blob(gcs_transcript_path)
        transcript_blob.upload_from_string(transcript_content, content_type='text/plain')
        logger.info(f"Transcription saved to gs://{TRANSCRIPTION_OUTPUT_BUCKET}/{gcs_transcript_path}")

        # --- New: Gemini LLM Analysis ---
        genai.configure(api_key=GEMINI_API_KEY) # Re-added API key configuration
        model = genai.GenerativeModel('gemini-2.5-pro')

        analysis_instructions = """
        Analyze the following video transcript for a high ticket digital item sale for flaws in the sales process. The purpose of the seller here is to move the prospect through the Key stages/Beliefs to help them make 	a sales decision:
	Pain – Clarify their main problem.
	Doubt – Why they haven't solved it on their own.
	Cost – The hidden cost of staying stuck.
	Desire – Their ultimate desired outcome.
	Support – Assurance they'll get necessary help.
	Handle Partner Indecision: Ask if they have support of their partners or parents so that the prospect can't leave the call at the end saying they need to consult them and get back without making a commitment on the call itself .
	Trust – Confidence in you and your solution. Provide a concise summary, identify the main topics discussed,
        and list any key action items or conclusions. Try to infer the roles
        of the prospect and the salesperson and give actionable feedback with specific parts and what did the seller miss or could improve during the conversation .
        """

        full_prompt = f"{analysis_instructions}\n\nTranscript:\n{transcript_content}"

        logger.info("Sending prompt to Gemini LLM for analysis...")
        # Added logging for the prompt length
        logger.info(f"Length of full_prompt sent to Gemini: {len(full_prompt)} characters.")
        if len(full_prompt) < 500 or len(full_prompt) > 10000: # Log full prompt if it's very short or potentially too long
            logger.info(f"Full prompt sent to Gemini (first 1000 chars): \n{full_prompt[:1000]}...")
            if len(full_prompt) > 10000:
                logger.warning("Prompt is very long, consider shortening it if not all content is critical.")


        gemini_response = model.generate_content(full_prompt)

        # Access the text from the Gemini response
        analysis_content = gemini_response.text
        logger.info("Gemini analysis complete.")
        logger.info(f"Length of Gemini analysis content: {len(analysis_content)} characters.")
        logger.info(f"Partial Analysis (first 200 chars): {analysis_content[:200]}...")

        # 6. Save the Gemini analysis output to GCS
        analysis_blob = output_bucket.blob(gcs_analysis_path)
        analysis_blob.upload_from_string(analysis_content, content_type='text/plain')
        logger.info(f"Gemini analysis saved to gs://{TRANSCRIPTION_OUTPUT_BUCKET}/{gcs_analysis_path}")

    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg command failed: {e.stderr.decode()}")
        raise
    except Exception as e:
        logger.error(f"Error during transcription or analysis process: {e}")
        raise
    finally:
        # Clean up temporary files
        if os.path.exists(local_video_path):
            os.remove(local_video_path)
            logger.info(f"Cleaned up {local_video_path}")
        if os.path.exists(local_audio_path):
            os.remove(local_audio_path)
            logger.info(f"Cleaned up {local_audio_path}")

# requirements.txt for the Cloud Function
# google-cloud-storage
# google-cloud-speech
# functions-framework
# google-generativeai
# google-api-python-client
# google-auth
