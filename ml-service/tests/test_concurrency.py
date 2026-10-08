from concurrent.futures import ThreadPoolExecutor
import io

from PIL import Image


def test_parallel_inference_is_consistent_and_does_not_leak(client):
    runtime = client.app.state.runtime
    original = runtime.describer.predict
    seen = []

    def wrapped(image, confirmed=None):
        result = original(image, confirmed=confirmed)
        seen.append(result)
        return result

    runtime.describer.predict = wrapped
    samples = []
    for color in ((250, 20, 20), (20, 230, 40), (25, 30, 235), (240, 230, 20)):
        buffer = io.BytesIO()
        Image.new("RGB", (256, 256), color).save(buffer, "JPEG")
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
    for index, response in results:
        p = response.json()["prediction"]
        assert p == baseline[index]
        assert p["description_fields"]["color"] == "unknown"
        assert "user_confirmed" not in p["description_provenance"].values()
