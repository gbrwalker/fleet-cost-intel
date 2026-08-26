"""Download raw files. Does not interpret them.

Idempotency layer 1 of 3: every downloaded file is hashed and compared with the
last ingestion. Identical hash means the pipeline exits successfully without
reprocessing — which is the common case, because ANP does not republish hourly.

The other two layers are in `transform` (merge by natural key) and `publish`
(atomic write).
"""
from __future__ import annotations

import gzip
import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

RAW = Path("data/raw")
MANIFESTO = RAW / "manifest.json"
UA = "fleet-cost-intel/0.1 (+https://github.com/gbrwalker/fleet-cost-intel)"


@dataclass
class Baixado:
    url: str
    caminho: Path
    sha256: str
    mudou: bool


def _manifesto() -> dict[str, str]:
    if MANIFESTO.exists():
        return json.loads(MANIFESTO.read_text(encoding="utf-8"))
    return {}


def _gravar_manifesto(m: dict[str, str]) -> None:
    MANIFESTO.parent.mkdir(parents=True, exist_ok=True)
    MANIFESTO.write_text(json.dumps(m, indent=2, sort_keys=True), encoding="utf-8")


def _nome_local(url: str) -> Path:
    return RAW / (url.rsplit("/", 2)[-2] + "-" + url.rsplit("/", 1)[-1] + ".gz")


def buscar(url: str, *, tentativas: int = 4, timeout: int = 120) -> bytes:
    """GET with exponential backoff.

    Retries on transport errors and on 5xx. A 404 is NOT retried: the file
    genuinely is not published yet, and hammering a government server for
    something that does not exist is how an IP gets blocked.
    """
    espera = 2.0
    ultimo: Exception | None = None
    for tentativa in range(1, tentativas + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            ultimo = e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            ultimo = e
        if tentativa < tentativas:
            time.sleep(espera)
            espera *= 2
    raise RuntimeError(f"failed after {tentativas} attempts: {url}") from ultimo


def baixar(urls: list[str]) -> list[Baixado]:
    """Download each URL, skipping ones whose content has not changed.

    A 404 is tolerated and logged: monthly files for a month that has not been
    published yet are expected to be missing, and that is not a failure.
    """
    RAW.mkdir(parents=True, exist_ok=True)
    manifesto = _manifesto()
    out: list[Baixado] = []
    for url in urls:
        try:
            corpo = buscar(url)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                print(f"  [skip 404] {url.rsplit('/', 1)[-1]} — not published yet")
                continue
            raise
        digest = hashlib.sha256(corpo).hexdigest()
        destino = _nome_local(url)
        mudou = manifesto.get(url) != digest
        if mudou or not destino.exists():
            destino.write_bytes(gzip.compress(corpo))
            manifesto[url] = digest
        print(f"  [{'new ' if mudou else 'same'}] {destino.name} "
              f"({len(corpo) / 1e6:.1f} MB)")
        out.append(Baixado(url, destino, digest, mudou))
    _gravar_manifesto(manifesto)
    return out


def ler(caminho: Path) -> bytes:
    return gzip.decompress(caminho.read_bytes())
