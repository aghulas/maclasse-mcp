from PIL import Image, ImageDraw

from maclasse_mcp.preparer import est_silhouette, optimiser_jpeg, POIDS_MAX


def test_silhouette_et_optimisation(tmp_path):
    grise = tmp_path / "grise.jpg"
    im = Image.new("RGB", (400, 533), (240, 240, 240))
    ImageDraw.Draw(im).ellipse((100, 50, 300, 300), fill=(210, 210, 210))
    im.save(grise, "JPEG", quality=95)
    assert est_silhouette(grise)

    import random
    photo = tmp_path / "photo.jpg"
    im = Image.new("RGB", (400, 533))
    im.putdata([(random.randrange(256), random.randrange(256), random.randrange(256)) for _ in range(400 * 533)])
    im.save(photo, "JPEG", quality=100)
    assert not est_silhouette(photo)
    assert photo.stat().st_size > POIDS_MAX
    out = tmp_path / "out.jpg"
    taille = optimiser_jpeg(photo, out)
    assert taille <= POIDS_MAX or taille < photo.stat().st_size
    assert Image.open(out).size == (400, 533)
