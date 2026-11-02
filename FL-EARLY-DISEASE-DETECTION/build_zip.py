import zipfile, os

with zipfile.ZipFile("lambda/api/api_deploy.zip", "w", zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk("deploy_stage"):
        for f in files:
            full_path = os.path.join(root, f)
            arcname = os.path.relpath(full_path, "deploy_stage").replace(os.sep, "/")
            zf.write(full_path, arcname)
print("done")
