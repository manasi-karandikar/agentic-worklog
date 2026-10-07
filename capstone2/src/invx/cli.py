"""invx CLI: `invx extract <pdf|dir>` and `invx eval`."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from .evaluate import FIELDS, score_doc, summarize
from .metrics import append_jsonl
from .tools import extract_one, make_client

load_dotenv()
app = typer.Typer(add_completion=False, help="Extract structured data from invoice PDFs with Gemini.")
console = Console()
STATUS_STYLE = {"ok": "green", "needs_review": "yellow", "failed": "red"}


def _results_table(rows: list[tuple]) -> Table:
    t = Table(title="Results")
    for col in ["file", "status", "tries", "latency s", "tokens in/out", "cost $ (notional)", "review reasons"]:
        t.add_column(col)
    for res, m in rows:
        t.add_row(res.file, f"[{STATUS_STYLE[res.status]}]{res.status}[/]", str(res.attempts),
                  f"{m.latency_s:.1f}", f"{m.prompt_tokens}/{m.output_tokens}", f"{m.notional_cost_usd:.5f}",
                  res.error or "; ".join(res.review_reasons))
    return t


def _run(pdfs: list[Path], out_dir: Path) -> list[tuple]:
    client = make_client()
    (out_dir / "outputs").mkdir(parents=True, exist_ok=True)
    rows = []
    for pdf in pdfs:
        console.print(f"[dim]processing {pdf.name}...[/]")
        res, m = extract_one(pdf, client)
        (out_dir / "outputs" / f"{pdf.stem}.json").write_text(res.model_dump_json(indent=2), encoding="utf-8")
        append_jsonl(out_dir / "metrics.jsonl", m)
        rows.append((res, m))
    return rows


@app.command()
def extract(path: Path = typer.Argument(..., help="A PDF file or a directory of PDFs"),
            out: Path = typer.Option(None, help="Output dir (default runs/<timestamp>)")):
    """Extract invoices to JSON and print a results table."""
    pdfs = sorted(path.glob("*.pdf")) if path.is_dir() else [path]
    if not pdfs or not all(p.is_file() for p in pdfs):
        console.print(f"[red]No PDFs found at '{path}'. Pass a .pdf file or a directory containing PDFs.[/]")
        raise typer.Exit(1)
    out = out or Path("runs") / datetime.now().strftime("%Y%m%d-%H%M%S")
    rows = _run(pdfs, out)
    console.print(_results_table(rows))
    console.print(f"JSON + metrics written to {out}")


@app.command("eval")
def eval_cmd(pdf_dir: Path = Path("data/pdfs"), label_dir: Path = Path("data/labels"),
             out: Path = typer.Option(None, help="Output dir (default runs/<timestamp>)")):
    """Process all labelled PDFs, then report field accuracy, retry rate, cost and latency."""
    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if not pdfs:
        console.print(f"[red]No PDFs in {pdf_dir}. Run `python scripts/gen_synthetic.py` first.[/]")
        raise typer.Exit(1)
    unlabelled = [p for p in pdfs if not (label_dir / f"{p.stem}.json").is_file()]
    if unlabelled:
        console.print(f"[yellow]Skipping {len(unlabelled)} PDF(s) with no label in {label_dir}: "
                      f"{', '.join(p.name for p in unlabelled)}[/]")
        pdfs = [p for p in pdfs if p not in unlabelled]
    if not pdfs:
        console.print(f"[red]No labelled PDFs. Add <stem>.json labels to {label_dir}.[/]")
        raise typer.Exit(1)
    out = out or Path("runs") / datetime.now().strftime("%Y%m%d-%H%M%S")
    rows = _run(pdfs, out)
    console.print(_results_table(rows))

    scored = []
    for res, m in rows:
        label = json.loads((label_dir / f"{Path(res.file).stem}.json").read_text(encoding="utf-8"))
        scored.append({"file": res.file, "status": res.status, "attempts": res.attempts,
                       "latency_s": m.latency_s, "notional_cost_usd": m.notional_cost_usd,
                       "expected_needs_review": label["expected_needs_review"], "defect": label["defect"],
                       "scores": score_doc(res.invoice, label)})
    s = summarize(scored)
    (out / "results.json").write_text(json.dumps({"summary": s, "docs": scored}, indent=2), encoding="utf-8")

    acc = Table(title="Field-level accuracy")
    acc.add_column("field"); acc.add_column("accuracy", justify="right")
    for f in FIELDS:
        acc.add_row(f, f"{s['field_accuracy'][f]:.0%}")
    console.print(acc)
    if s["extra_field_accuracy"]:
        console.print("GST fields: " + " | ".join(f"{k} {v:.0%}" for k, v in s["extra_field_accuracy"].items()))
    bd = Table(title="By defect type")
    for c in ["defect", "docs", "expected review", "flagged", "flagged correctly", "field acc"]:
        bd.add_column(c)
    for d, g in sorted(s["by_defect"].items()):
        bd.add_row(d, str(g["docs"]), str(g["expected_review"]), str(g["flagged"]), str(g["flagged_correctly"]),
                   f"{g['field_accuracy']:.0%}")
    console.print(bd)
    fmt = lambda v: "n/a" if v is None else f"{v:.0%}"
    console.print(
        f"overall field accuracy {s['overall_field_accuracy']:.1%} | retry rate {s['retry_rate']:.0%} | "
        f"failed {s['failed']} | needs_review precision {fmt(s['review_precision'])} recall {fmt(s['review_recall'])}\n"
        f"cost/doc ${s['cost_per_doc_usd']:.5f} (notional) | latency median {s['median_latency_s']:.1f}s "
        f"p95 {s['p95_latency_s']:.1f}s\nresults: {out / 'results.json'}")


if __name__ == "__main__":
    app()
