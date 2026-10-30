from concurrent.futures import ThreadPoolExecutor
import io
import threading
import time

from PIL import Image, ImageDraw


def test_parallel_inference_is_consistent_and_does_not_leak(client):
    runtime = client.app.state.runtime
    original = runtime.describer.predict
    seen = []
    guard = threading.Lock()
    active, maximum_active = 0, 0

    def wrapped(image, confirmed=None):
        nonlocal active, maximum_active
        with guard:
            active += 1
            maximum_active = max(maximum_active, active)
        try:
            time.sleep(0.005)  # Encourage overlap if the service lock regresses.
            result = original(image, confirmed=confirmed)
            seen.append(result)
            return result
        finally:
            with guard:
                active -= 1

    runtime.describer.predict = wrapped
    samples = []
    for index, color in enumerate(((250, 20, 20), (20, 230, 40), (25, 30, 235), (240, 230, 20))):
        buffer = io.BytesIO()
        image = Image.new("RGB", (256, 320), (245, 244, 238))
        draw = ImageDraw.Draw(image)
        if index % 2:
            draw.polygon([(90, 35), (165, 35), (200, 285), (60, 285)], fill=color)
        else:
            draw.polygon([(55, 70), (95, 35), (160, 35), (200, 70), (175, 120), (160, 110), (160, 270), (95, 270), (95, 110), (80, 120)], fill=color)
        image.save(buffer, "JPEG")
        samples.append(buffer.getvalue())

    try:
        baseline = [client.post(
            "/analyze", files={"image": ("baseline.jpg", data, "image/jpeg")}
        ).json()["prediction"] for data in samples]
        workload = list(enumerate(samples * 3))
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda item: (
                item[0] % len(samples),
                client.post("/analyze", files={
                    "image": ("parallel.jpg", item[1], "image/jpeg")
                }),
            ), workload))
    finally:
        runtime.describer.predict = original

    assert all(response.status_code == 200 for _, response in results)
    assert len(seen) == len(baseline) + len(results)
    assert maximum_active == 1  # The complete mutable-hook operation is serialized.
    for index, response in results:
        p = response.json()["prediction"]
        assert p == baseline[index]
        assert p["description_fields"]["color"] == "unknown"
        assert "user_confirmed" not in p["description_provenance"].values()
