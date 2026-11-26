from ..tiktok import video_url, worker
from .video_download_page import VideoDownloadPage


class TikTokPage(VideoDownloadPage):
    def __init__(self, context):
        super().__init__(context, service="TikTok", link_placeholder="https://www.tiktok.com/@user/video/…",
                         parse_url=video_url, task_worker=worker)
