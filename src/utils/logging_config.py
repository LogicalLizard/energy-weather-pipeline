import logging


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # httpx logs every single request at INFO, that drowns out our own messages
    logging.getLogger("httpx").setLevel(logging.WARNING)
