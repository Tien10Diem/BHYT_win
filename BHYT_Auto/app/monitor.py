class StableResult:
    """Chỉ phát một lần cho mỗi lần bấm Tra cứu quan sát được."""
    def __init__(self, seconds=3):
        self.seconds = seconds
        self.key = None
        self.since = None
        self.emitted = set()

    def consider(self, text, row_token, submission, now):
        if not submission or not text:
            self.key = None
            self.since = None
            return None
        attempt = (row_token, submission)
        if attempt in self.emitted:
            return None
        key = (attempt, text)
        if key != self.key:
            self.key, self.since = key, now
            return None
        if now - self.since < self.seconds:
            return None
        self.emitted.add(attempt)
        return text
