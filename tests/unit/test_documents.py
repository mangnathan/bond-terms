import csv
from pathlib import Path

import pyarrow.parquet as pq

from bond_terms.documents import DocumentRef, collect, download_url, extract_pages, load_documents
from bond_terms.esma import DownloadedFile, SourceError, sha256_of


def tiny_pdf(*pages: str) -> bytes:
    """PDF minimal, une page par texte, avec une police standard."""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(len(pages)))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    font = 3 + 2 * len(pages)
    for i, text in enumerate(pages):
        content = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode() if text else b""
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 200] /Contents {4 + 2 * i} 0 R "
            f"/Resources << /Font << /F1 {font} 0 R >> >> >>".encode()
        )
        objects.append(
            b"<< /Length "
            + str(len(content)).encode()
            + b" >>\nstream\n"
            + content
            + b"\nendstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)


def test_pages_are_extracted_in_order(tmp_path: Path) -> None:
    path = tmp_path / "doc.pdf"
    path.write_bytes(tiny_pdf("Maturity Date: 7 September 2029", "", "Rate of Interest: 3.25"))
    pages = extract_pages(path)
    assert len(pages) == 3
    assert "Maturity Date" in pages[0]
    assert pages[1].strip() == ""


def test_documents_are_listed_once(tmp_path: Path) -> None:
    split = tmp_path / "decoupage.csv"
    with split.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["document_id", "rfss_file_id", "rfss_checksum", "jeu"]
        )
        writer.writeheader()
        writer.writerow(
            {"document_id": "2", "rfss_file_id": "20", "rfss_checksum": "b", "jeu": "test"}
        )
        writer.writerow(
            {"document_id": "1", "rfss_file_id": "10", "rfss_checksum": "a", "jeu": "developpement"}
        )
        writer.writerow(
            {"document_id": "2", "rfss_file_id": "20", "rfss_checksum": "b", "jeu": "test"}
        )
    assert [d.document_id for d in load_documents(split)] == ["1", "2"]
    assert download_url(DocumentRef("1", "10", "a", "developpement")).endswith(
        "downloadFile?fileId=10&checksum=a"
    )


class FakeRegister:
    def __init__(self, files: dict[str, bytes | Exception]) -> None:
        self.files = files

    def download(self, url: str, destination: Path) -> DownloadedFile:
        content = self.files[destination.stem]
        if isinstance(content, Exception):
            raise content
        destination.write_bytes(content)
        return DownloadedFile(destination, len(content), sha256_of(destination))


def test_collect_checks_quality_and_keeps_failures(tmp_path: Path) -> None:
    split = tmp_path / "decoupage.csv"
    with split.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["document_id", "rfss_file_id", "rfss_checksum", "jeu"]
        )
        writer.writeheader()
        for doc_id, split_name in [
            ("1", "developpement"),
            ("2", "developpement"),
            ("3", "test"),
            ("4", "test"),
        ]:
            writer.writerow(
                {
                    "document_id": doc_id,
                    "rfss_file_id": doc_id,
                    "rfss_checksum": "x",
                    "jeu": split_name,
                }
            )
    register = FakeRegister(
        {
            "1": tiny_pdf("Maturity Date: 2029-09-07", "Issue Price: 99.5"),
            "2": tiny_pdf("Date d'echeance : 2030", ""),
            "3": b"<html>maintenance</html>",
            "4": SourceError("HTTP 503"),
        }
    )
    summary = collect(register, split, tmp_path / "data", tmp_path / "out")  # type: ignore[arg-type]
    assert summary["developpement"] == {
        "documents": 2,
        "lus": 2,
        "erreurs": {},
        "pages_mediane": 2.0,
        "documents_avec_pages_sans_texte": 1,
        "documents_sans_rubrique_echeance": 0,
    }
    assert summary["test"]["lus"] == 0
    assert summary["test"]["erreurs"] == {
        "le registre n'a pas renvoyé un PDF": 1,
        "téléchargement": 1,
    }
    assert not (tmp_path / "data/raw/pdf/3.pdf").exists()
    pages = pq.read_table(tmp_path / "data/interim/textes/pages.parquet").to_pylist()
    assert [(p["document_id"], p["page"]) for p in pages] == [
        ("1", "1"),
        ("1", "2"),
        ("2", "1"),
        ("2", "2"),
    ]
    with (tmp_path / "out" / "pdf-controle.csv").open(encoding="utf-8") as f:
        assert "texte" not in next(csv.reader(f))
