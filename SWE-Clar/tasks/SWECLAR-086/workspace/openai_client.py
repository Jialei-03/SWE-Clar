"""External client seam; live service access is disabled in the benchmark."""


def get_openai_client():
    raise RuntimeError("live OpenAI access is disabled in the benchmark")

