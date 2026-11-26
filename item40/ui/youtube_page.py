from ..youtube import video_url, worker
from .video_download_page import VideoDownloadPage


class YouTubePage(VideoDownloadPage):
    def __init__(self, context):
        super().__init__(context, service="YouTube", link_placeholder="https://www.youtube.com/watch?v=…",
                         parse_url=video_url, task_worker=worker)
