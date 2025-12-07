"""WebSocket endpoint for video captioning with Moondream and Deepgram STT.

Uses parallel processing pattern: separate queues and tasks for audio and video streams.
Includes video clip encoding and S3 storage for frame persistence.
"""

import asyncio
import base64
import json
import os
from datetime import datetime

from deepgram import AsyncDeepgramClient
from deepgram.core.events import EventType
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.clip_encoder import ClipEncoder
from app.core.db import async_session_maker
from app.core.log_config import logger
from app.core.mem0_client import mem0_manager
from app.core.moondream_processor import moondream_processor
from app.core.s3_utils import s3_manager
from app.crud import create_video_clip

router = APIRouter()


@router.websocket("/ws/video-caption")
async def video_caption_endpoint(websocket: WebSocket):
    """WebSocket endpoint for video frame captioning and audio transcription.

    Uses parallel processing: separate queues and tasks for audio/video streams.
    Stores captions and transcripts separately in Mem0.

    Message format (incoming):
        {"type": "image", "image": "<base64 jpeg>"}
        {"type": "audio", "audio": "<base64 PCM 24kHz linear16>"}
        or Ray-Ban/Android format:
        {"image": "data:image/jpeg;base64,<base64>", "processor": 0}
        {"type": "audio_stream", "audio_chunk": "<base64 PCM 24kHz>"}
        {"type": "audio_stream_stop"}

    Message format (outgoing):
        {"type": "moondream_caption", "timestamp": "...", "description": "...", "frame_number": N}
        {"type": "transcript", "text": "...", "is_final": true, "speaker": "Speaker 0"}
    """
    await websocket.accept()
    logger.info("Video caption WebSocket connected")

    # Session ID for tracking
    session_id = f"vc_{id(websocket)}_{int(datetime.now().timestamp())}"

    # Create separate queues for parallel processing
    audio_queue: asyncio.Queue = asyncio.Queue()
    image_queue: asyncio.Queue = asyncio.Queue()
    upload_queue: asyncio.Queue = asyncio.Queue()

    # Batch buffers for Mem0 (flush every 30 seconds instead of immediate push)
    transcript_batch: list[dict] = []
    caption_batch: list[dict] = []

    # Counters for Mem0 requests
    mem0_transcript_requests = 0
    mem0_caption_requests = 0
    mem0_total_transcripts = 0
    mem0_total_captions = 0

    # Video clip encoder (10-second clips at 24 FPS)
    clip_encoder = ClipEncoder(clip_duration_sec=10.0, fps=24)

    # Track current clip metadata for Mem0 linking
    current_clip_metadata: dict | None = None

    # Shared state for Deepgram socket
    deepgram_connection = None
    deepgram_running = False

    # Transcript callback
    async def on_transcript(text: str, is_final: bool, speaker: str):
        """Handle transcripts from Deepgram - stores separately in Mem0."""
        # Send to client
        await websocket.send_text(json.dumps({
            "type": "transcript",
            "text": text,
            "is_final": is_final,
            "speaker": speaker
        }))

        # Highlight in logs
        if is_final:
            logger.info(f">>> [STT FINAL] [{speaker}] {text}")
            # Accumulate transcript for batched Mem0 push (every 30 seconds)
            transcript_batch.append({
                "timestamp": datetime.now().isoformat(),
                "speaker": speaker,
                "text": text,
                "session_id": session_id
            })
        else:
            logger.info(f"    [STT interim] [{speaker}] {text}")

    # === Parallel Processing Tasks ===

    async def message_router():
        """Routes incoming WebSocket messages to appropriate queue."""
        msg_count = 0
        try:
            while True:
                data = await websocket.receive_text()
                msg = json.loads(data)
                msg_type = msg.get("type", "")
                msg_count += 1

                # Log every 50th message to avoid spam
                if msg_count == 1 or msg_count % 50 == 0:
                    logger.info(f"[Router] Msg #{msg_count}: type={msg_type}")

                # Route audio messages
                if msg_type in ("audio", "audio_stream") or "audio_chunk" in msg or msg_type == "audio_stream_stop":
                    await audio_queue.put(msg)
                # Route image messages
                elif "image" in msg:
                    await image_queue.put(msg)

        except WebSocketDisconnect:
            # Send poison pills to signal shutdown
            await audio_queue.put(None)
            await image_queue.put(None)
            raise

    async def audio_processor():
        """Processes audio chunks - sends to Deepgram STT."""
        nonlocal deepgram_connection, deepgram_running
        chunk_count = 0

        while True:
            msg = await audio_queue.get()
            if msg is None:
                break  # Poison pill - shutdown

            msg_type = msg.get("type")
            if msg_type == "audio_stream_stop":
                logger.info(f"[Audio] Stream stopped by client (processed {chunk_count} chunks)")
                continue

            audio_b64 = msg.get("audio_chunk") or msg.get("audio")
            if audio_b64 and deepgram_connection and deepgram_running:
                chunk_count += 1
                # Log every 10 chunks to reduce clutter
                if chunk_count % 10 == 0:
                    logger.info(f"[Audio] Chunk #{chunk_count} forwarded to Deepgram")

                # Deepgram takes raw bytes directly
                audio_bytes = base64.b64decode(audio_b64)
                try:
                    await deepgram_connection.send_media(audio_bytes)
                except Exception as e:
                    logger.error(f"[Deepgram] Error sending audio: {e}")

    async def upload_processor():
        """Separate task for S3 uploads + PostgreSQL storage."""
        nonlocal current_clip_metadata

        # Check S3 configuration on startup
        if not s3_manager.bucket_name:
            logger.warning("[Upload] S3_BUCKET_NAME not configured - clips will NOT be stored!")
        else:
            logger.info(f"[Upload] S3 configured: bucket={s3_manager.bucket_name}")

        while True:
            item = await upload_queue.get()
            if item is None:
                logger.info("[Upload] Received shutdown signal")
                break  # Shutdown signal

            video_bytes, start_time_str, end_time_str, clip_index, thumbnail_bytes = item
            logger.info(f"[Upload] Processing clip {clip_index}: {len(video_bytes)} bytes, thumbnail {len(thumbnail_bytes)} bytes")

            if not s3_manager.bucket_name:
                logger.warning(f"[Upload] Skipping clip {clip_index} - no S3 bucket configured")
                continue

            try:
                # 1. Upload video clip to S3
                s3_metadata = await s3_manager.upload_clip(
                    session_id=session_id,
                    clip_index=clip_index,
                    video_bytes=video_bytes,
                    start_time=start_time_str,
                    end_time=end_time_str,
                )

                # 2. Upload thumbnail to S3
                thumbnail_s3_key = None
                if thumbnail_bytes:
                    thumbnail_s3_key = await s3_manager.upload_thumbnail(
                        session_id=session_id,
                        clip_index=clip_index,
                        image_bytes=thumbnail_bytes,
                    )

                # 3. Store in PostgreSQL for time-range queries
                async with async_session_maker() as db_session:
                    clip_record = await create_video_clip(
                        session=db_session,
                        session_id=session_id,
                        clip_index=clip_index,
                        s3_key=s3_metadata["s3_key"],
                        s3_bucket=s3_metadata["s3_bucket"],
                        start_time=datetime.fromisoformat(start_time_str),
                        end_time=datetime.fromisoformat(end_time_str),
                        thumbnail_s3_key=thumbnail_s3_key,
                    )
                    logger.info(f"[DB] Clip {clip_index} stored: id={clip_record.id}, thumb={thumbnail_s3_key}")

                current_clip_metadata = s3_metadata
                logger.info(f"[Upload] Clip {clip_index} complete: {s3_metadata['s3_key']}")

            except Exception as e:
                logger.error(f"[Upload] Failed for clip {clip_index}: {e}")

    async def image_processor():
        """Processes video frames - Moondream captioning + clip buffering."""
        while True:
            msg = await image_queue.get()
            if msg is None:
                # Flush remaining frames on disconnect
                final_clip = clip_encoder.flush()
                if final_clip:
                    await upload_queue.put(final_clip)
                await upload_queue.put(None)  # Signal upload_processor to stop
                break

            image_b64 = msg.get("image")
            if not image_b64:
                continue

            # Strip data URL prefix if present (Ray-Ban format)
            if isinstance(image_b64, str) and image_b64.startswith("data:"):
                image_b64 = image_b64.split(",", 1)[1] if "," in image_b64 else image_b64

            # Decode for both Moondream and clip encoding
            image_bytes = base64.b64decode(image_b64)
            timestamp = datetime.now()

            # Add to clip buffer (ALL frames for smooth video)
            clip_result = clip_encoder.add_frame(image_bytes, timestamp)
            if clip_result:
                # Clip ready - queue for upload (non-blocking)
                logger.info("[Clip] Clip ready! Queuing for upload...")
                await upload_queue.put(clip_result)

            # Log frame buffer status periodically
            if len(clip_encoder.frames) % 50 == 0 and len(clip_encoder.frames) > 0:
                elapsed = (timestamp - clip_encoder.clip_start_time).total_seconds() if clip_encoder.clip_start_time else 0
                logger.info(f"[Clip] Buffer: {len(clip_encoder.frames)} frames, {elapsed:.1f}s elapsed")

            # Process with Moondream (throttled internally to every 10th frame)
            result = await moondream_processor.process_frame(image_b64)

            if result:
                # Accumulate caption for batched Mem0 push (every 30 seconds)
                caption_batch.append({
                    "caption": {
                        "timestamp": result["timestamp"],
                        "description": result["description"],
                        "frame_number": result["frame_number"],
                    },
                    "clip_metadata": current_clip_metadata,
                })

                # Send to client (include clip reference if available)
                response = {
                    "type": "moondream_caption",
                    "timestamp": result["timestamp"],
                    "description": result["description"],
                    "frame_number": result["frame_number"],
                }
                if current_clip_metadata:
                    response["clip_key"] = current_clip_metadata.get("s3_key")

                await websocket.send_text(json.dumps(response))
                logger.info(
                    f"[Moondream] #{result['frame_number']} | {result['description'][:50]}..."
                )

    async def mem0_batch_processor():
        """Flushes accumulated transcripts and captions to Mem0 every 30 seconds."""
        nonlocal mem0_transcript_requests, mem0_caption_requests
        nonlocal mem0_total_transcripts, mem0_total_captions

        while True:
            await asyncio.sleep(30)

            # Snapshot and clear buffers
            transcripts_to_push = transcript_batch.copy()
            captions_to_push = caption_batch.copy()
            transcript_batch.clear()
            caption_batch.clear()

            if not transcripts_to_push and not captions_to_push:
                logger.debug("[Mem0] No data to batch push")
                continue

            # Combine transcripts into single coherent text
            if transcripts_to_push:
                combined_transcript = " ".join(t["text"] for t in transcripts_to_push)
                # Aggregate speakers
                speakers = list({t["speaker"] for t in transcripts_to_push})
                speaker_str = speakers[0] if len(speakers) == 1 else "multiple"
                await mem0_manager.store_transcript({
                    "timestamp": transcripts_to_push[0]["timestamp"],
                    "speaker": speaker_str,
                    "text": combined_transcript,
                    "session_id": session_id,
                })
                mem0_transcript_requests += 1
                mem0_total_transcripts += len(transcripts_to_push)
                logger.info(f"[Mem0] Batch transcript: {len(transcripts_to_push)} utterances -> '{combined_transcript[:60]}...'")

            # Combine captions into grouped visual context
            if captions_to_push:
                descriptions = [c["caption"]["description"] for c in captions_to_push]
                combined_description = " | ".join(descriptions)
                # Use the last clip metadata
                last_clip = captions_to_push[-1].get("clip_metadata")
                await mem0_manager.store_caption_with_clip(
                    caption={
                        "timestamp": captions_to_push[0]["caption"]["timestamp"],
                        "description": combined_description,
                        "frame_number": captions_to_push[-1]["caption"]["frame_number"],
                    },
                    clip_metadata=last_clip,
                )
                mem0_caption_requests += 1
                mem0_total_captions += len(captions_to_push)
                logger.info(f"[Mem0] Batch captions: {len(captions_to_push)} frames -> '{combined_description[:60]}...'")

            logger.info(f"[Mem0] Batch pushed: {len(transcripts_to_push)} transcripts, {len(captions_to_push)} captions")

    async def flush_mem0_batch():
        """Flush any remaining buffered data on disconnect."""
        nonlocal mem0_transcript_requests, mem0_caption_requests
        nonlocal mem0_total_transcripts, mem0_total_captions

        if not transcript_batch and not caption_batch:
            return

        logger.info(f"[Mem0] Flushing final batch: {len(transcript_batch)} transcripts, {len(caption_batch)} captions")

        if transcript_batch:
            combined_transcript = " ".join(t["text"] for t in transcript_batch)
            speakers = list({t["speaker"] for t in transcript_batch})
            speaker_str = speakers[0] if len(speakers) == 1 else "multiple"
            await mem0_manager.store_transcript({
                "timestamp": transcript_batch[0]["timestamp"],
                "speaker": speaker_str,
                "text": combined_transcript,
                "session_id": session_id,
            })
            mem0_transcript_requests += 1
            mem0_total_transcripts += len(transcript_batch)

        if caption_batch:
            descriptions = [c["caption"]["description"] for c in caption_batch]
            combined_description = " | ".join(descriptions)
            last_clip = caption_batch[-1].get("clip_metadata")
            await mem0_manager.store_caption_with_clip(
                caption={
                    "timestamp": caption_batch[0]["caption"]["timestamp"],
                    "description": combined_description,
                    "frame_number": caption_batch[-1]["caption"]["frame_number"],
                },
                clip_metadata=last_clip,
            )
            mem0_caption_requests += 1
            mem0_total_captions += len(caption_batch)

    # Initialize Deepgram
    deepgram_api_key = os.environ.get("DEEPGRAM_API_KEY")
    if not deepgram_api_key:
        logger.error("[Deepgram] DEEPGRAM_API_KEY not set!")
        await websocket.close()
        return

    client = AsyncDeepgramClient(api_key=deepgram_api_key)

    # Deepgram message handler (v5.x SDK)
    def on_message(message):
        """Handle Deepgram transcript messages."""
        try:
            msg_type = getattr(message, "type", "Unknown")
            logger.debug(f"[Deepgram] Received: {msg_type}")

            # Check for transcript in channel.alternatives
            if hasattr(message, 'channel'):
                alternatives = message.channel.alternatives
                if alternatives:
                    text = alternatives[0].transcript
                    is_final = getattr(message, 'is_final', False)

                    # Extract speaker info if available
                    speaker = "Speaker 0"
                    if alternatives[0].words:
                        first_word = alternatives[0].words[0]
                        if hasattr(first_word, 'speaker'):
                            speaker = f"Speaker {first_word.speaker}"

                    if text:
                        # Schedule the async callback
                        asyncio.create_task(on_transcript(text, is_final, speaker))
        except Exception as e:
            logger.error(f"[Deepgram] Error processing message: {e}")

    def on_error(error):
        logger.error(f"[Deepgram] Error: {error}")

    try:
        # Connect using v1 API with nova-3 model
        async with client.listen.v1.connect(
            model="nova-3",
            language="en-US",
            smart_format=True,
            interim_results=True,
            diarize=True,
            encoding="linear16",
            sample_rate=24000,
            channels=1
        ) as connection:
            deepgram_connection = connection
            deepgram_running = True

            # Register event handlers
            connection.on(EventType.OPEN, lambda _: logger.info("[Deepgram] Connection opened"))
            connection.on(EventType.MESSAGE, on_message)
            connection.on(EventType.CLOSE, lambda _: logger.info("[Deepgram] Connection closed"))
            connection.on(EventType.ERROR, on_error)

            logger.info("[Deepgram] Connected (Nova-3, diarize=true, 24kHz)")

            # Launch parallel tasks
            audio_task = asyncio.create_task(audio_processor())
            image_task = asyncio.create_task(image_processor())
            router_task = asyncio.create_task(message_router())
            upload_task = asyncio.create_task(upload_processor())
            mem0_task = asyncio.create_task(mem0_batch_processor())

            # Deepgram listener task - keeps connection alive
            async def deepgram_listener():
                try:
                    await connection.start_listening()
                except Exception as e:
                    logger.warning(f"[Deepgram] Listener ended: {e}")

            deepgram_task = asyncio.create_task(deepgram_listener())

            try:
                # Wait for any task to complete (usually router on disconnect)
                done, pending = await asyncio.wait(
                    [audio_task, image_task, router_task, deepgram_task, upload_task, mem0_task],
                    return_when=asyncio.FIRST_COMPLETED
                )

                # Retrieve results to avoid "Task exception never retrieved" warnings
                for task in done:
                    try:
                        task.result()
                    except WebSocketDisconnect:
                        pass  # Normal disconnect
                    except Exception as e:
                        logger.error(f"Task error: {e}")

                # Cancel pending tasks
                for task in pending:
                    task.cancel()

            except Exception as e:
                logger.error(f"Video caption error: {e}")

    except Exception as e:
        logger.error(f"[Deepgram] Connection error: {e}")
    finally:
        deepgram_running = False
        # Flush any remaining batched data to Mem0
        await flush_mem0_batch()
        # Print Mem0 request summary
        total_requests = mem0_transcript_requests + mem0_caption_requests
        logger.info("=" * 60)
        logger.info("[Mem0] SESSION SUMMARY")
        logger.info(f"[Mem0] Transcript requests: {mem0_transcript_requests} (batched {mem0_total_transcripts} utterances)")
        logger.info(f"[Mem0] Caption requests: {mem0_caption_requests} (batched {mem0_total_captions} frames)")
        logger.info(f"[Mem0] TOTAL API REQUESTS: {total_requests}")
        logger.info("=" * 60)
        logger.info("Video caption WebSocket closed")
