/**
 * ScriptToVideo API Client
 * Drop this file into your React project's src/ folder.
 * Usage: import api from './api-client/api'
 */

const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

const api = {
  /**
   * Generate audio from a script.
   * Pass ONE of: text, googleDocUrl, or file (File object)
   */
  async generateAudio({ text, googleDocUrl, file, voice = "alloy", speed = 1.0, language = "en-US" }) {
    const form = new FormData();
    if (text) form.append("text", text);
    if (googleDocUrl) form.append("google_doc_url", googleDocUrl);
    if (file) form.append("file", file);
    form.append("voice", voice);
    form.append("speed", String(speed));
    form.append("language", language);

    const res = await fetch(`${BASE_URL}/api/audio/generate`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) throw new Error(await res.text());
    return res.json(); // { job_id, status }
  },

  /**
   * Convert slides (PPTX) to a silent video.
   */
  async convertSlides({ file, slideDuration = 3, transition = "fade", resolution = "1920x1080" }) {
    const form = new FormData();
    form.append("file", file);
    form.append("slide_duration", String(slideDuration));
    form.append("transition", transition);
    form.append("resolution", resolution);

    const res = await fetch(`${BASE_URL}/api/slides/convert`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) throw new Error(await res.text());
    return res.json(); // { job_id, status }
  },

  /**
   * Merge the audio and slides video into the final MP4.
   */
  async mergeFiles({ audioFilename, videoFilename, syncMode = "pad" }) {
    const res = await fetch(`${BASE_URL}/api/merge/combine`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        audio_filename: audioFilename,
        video_filename: videoFilename,
        sync_mode: syncMode,
      }),
    });
    if (!res.ok) throw new Error(await res.text());
    return res.json(); // { job_id, status }
  },

  /**
   * Poll a job until it reaches 'done' or 'error'.
   * Calls onProgress(progress, message) on each update.
   */
  async pollUntilDone(jobId, onProgress, intervalMs = 1500) {
    return new Promise((resolve, reject) => {
      const poll = async () => {
        try {
          const res = await fetch(`${BASE_URL}/api/status/${jobId}`);
          const data = await res.json();
          if (onProgress) onProgress(data.progress, data.message);
          if (data.status === "done") return resolve(data.result);
          if (data.status === "error") return reject(new Error(data.error));
          setTimeout(poll, intervalMs);
        } catch (err) {
          reject(err);
        }
      };
      poll();
    });
  },

  /** Build a full download URL from a relative path returned by the API */
  downloadUrl(relativePath) {
    return `${BASE_URL}${relativePath}`;
  },
};

export default api;
