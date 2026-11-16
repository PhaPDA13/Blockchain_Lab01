"""Package the files required for a Lab 01 submission."""
import argparse
import shutil
import zipfile
from pathlib import Path


REQUIRED_ITEMS = (
    "src",
    "tests",
    "logs",
    "config",
    "run_simulation.py",
    "requirements.txt",
    "pytest.ini",
    "README.md",
    "REPORT.pdf",
)
IGNORED_ITEMS = shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc", ".coverage")


def package(student_ids):
    if not student_ids:
        raise ValueError("Provide at least one student ID (MSSV).")
    if any(not student_id.isdigit() for student_id in student_ids):
        raise ValueError("Student IDs must contain digits only.")
    if len(set(student_ids)) != len(student_ids):
        raise ValueError("Student IDs must be unique.")

    project_dir = Path(__file__).resolve().parent
    folder_name = "Lab01_" + "_".join(student_ids)
    target_dir = project_dir / folder_name
    zip_path = project_dir / f"{folder_name}.zip"
    if target_dir.resolve().parent != project_dir:
        raise ValueError("The submission folder must stay inside the project directory.")

    if target_dir.exists() or zip_path.exists():
        raise FileExistsError(
            f"{folder_name} or its ZIP already exists; move it before packaging again."
        )

    missing = [name for name in REQUIRED_ITEMS if not (project_dir / name).exists()]
    if missing:
        raise FileNotFoundError("Required submission items are missing: " + ", ".join(missing))

    target_dir.mkdir()
    zip_created = False
    try:
        for item in REQUIRED_ITEMS:
            source = project_dir / item
            destination = target_dir / item
            if source.is_dir():
                shutil.copytree(source, destination, ignore=IGNORED_ITEMS)
            else:
                shutil.copy2(source, destination)

        archive_file = zipfile.ZipFile(zip_path, "x", zipfile.ZIP_DEFLATED)
        zip_created = True
        with archive_file as archive:
            for source in sorted(target_dir.rglob("*")):
                if source.is_file():
                    archive.write(source, source.relative_to(project_dir))
    except Exception:
        if target_dir.exists():
            shutil.rmtree(target_dir)
        if zip_created and zip_path.exists():
            zip_path.unlink()
        raise

    print(f"Created submission folder: {target_dir}")
    print(f"Created submission archive: {zip_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Package the Lab 01 submission.")
    parser.add_argument(
        "--ids",
        nargs="+",
        required=True,
        help="Student IDs, e.g. --ids 23120273 23120281 23120315 23120382",
    )
    args = parser.parse_args()
    package(args.ids)
