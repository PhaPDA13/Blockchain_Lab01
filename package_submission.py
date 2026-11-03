"""
Helper script to package the project according to Section 10 of Lab01.pdf:
"Students create a folder Lab01_ID1_ID2_ID3_ID4_ID5 containing:
src/, tests/, logs/, config/, README.md, REPORT.pdf
Compress the above folder into Lab01_ID1_ID2_ID3_ID4_ID5.zip for submission."
"""
import os
import shutil
import zipfile
import argparse


def package(student_ids):
    if not student_ids:
        raise ValueError("Must provide at least one student ID (MSSV).")

    folder_name = "Lab01_" + "_".join(student_ids)
    print(f"Preparing package: {folder_name} ...")

    target_dir = os.path.join(os.getcwd(), folder_name)
    if os.path.exists(target_dir):
        shutil.rmtree(target_dir)
    os.makedirs(target_dir)

    # Required items
    items_to_copy = ["src", "tests", "logs", "config", "README.md", "REPORT.pdf"]

    for item in items_to_copy:
        src_path = os.path.join(os.getcwd(), item)
        dst_path = os.path.join(target_dir, item)

        if os.path.isdir(src_path):
            shutil.copytree(src_path, dst_path)
            print(f"  [+] Copied folder: {item}/")
        elif os.path.isfile(src_path):
            shutil.copy2(src_path, dst_path)
            print(f"  [+] Copied file: {item}")
        else:
            if item == "REPORT.pdf":
                print(f"  [!] Note: {item} does not exist yet. Please put your report file before final zip.")
            else:
                print(f"  [!] Warning: {item} not found!")

    # Create zip
    zip_filename = f"{folder_name}.zip"
    with zipfile.ZipFile(zip_filename, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(target_dir):
            for file in files:
                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, os.getcwd())
                zipf.write(abs_path, rel_path)

    print(f"\nSuccessfully generated submission file: {zip_filename}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Package Lab 01 submission zip.")
    parser.add_argument(
        "--ids",
        nargs="+",
        required=True,
        help="List of student IDs, e.g. --ids 2310315 or --ids 2310315 2310316",
    )
    args = parser.parse_args()
    package(args.ids)
