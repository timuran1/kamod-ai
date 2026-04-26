import time

from byteplus_provider import BytePlusModelArk


class SeedanceAPI:
    """Backward-compatible Seedance client backed by official BytePlus ModelArk."""

    def __init__(self, api_key=None):
        self.client = BytePlusModelArk()
        if api_key:
            self.client.api_key = api_key

    def text_to_video(self, prompt, aspect_ratio="16:9", duration=5, quality="basic", generate_audio=True):
        return self.client.create_video_task(
            prompt,
            ratio=aspect_ratio,
            duration=duration,
            generate_audio=generate_audio,
            fast=str(quality).lower() in {"fast", "global-fast", "vip-fast"},
        )

    def image_to_video(
        self,
        prompt,
        images_list,
        aspect_ratio="16:9",
        duration=5,
        quality="basic",
        remove_watermark=False,
        generate_audio=True,
    ):
        return self.client.create_video_task(
            prompt,
            image_urls=images_list,
            ratio=aspect_ratio,
            duration=duration,
            generate_audio=generate_audio,
            fast=str(quality).lower() in {"fast", "global-fast", "vip-fast"},
            watermark=not bool(remove_watermark),
        )

    def extend_video(self, request_id, prompt="", duration=5, quality="basic"):
        return self.client.create_video_task(
            prompt or "Extend the provided reference video while preserving style and motion continuity.",
            video_urls=[request_id],
            duration=duration,
            fast=str(quality).lower() in {"fast", "global-fast", "vip-fast"},
        )

    def get_result(self, request_id):
        return self.client.get_task(request_id)

    def wait_for_completion(self, request_id, poll_interval=5, timeout=780):
        start = time.time()
        while time.time() - start < timeout:
            result = self.get_result(request_id)
            status = result.get("status")
            if status == "completed":
                return result
            if status == "failed":
                raise RuntimeError(result.get("error") or "Video generation failed")
            time.sleep(poll_interval)
        raise TimeoutError("Timed out waiting for video generation to complete.")


if __name__ == "__main__":
    api = SeedanceAPI()
    submission = api.text_to_video(
        prompt="A cinematic shot of a futuristic city with neon lights, 8k resolution",
        duration=5,
    )
    print(submission)
