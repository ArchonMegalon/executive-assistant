from pathlib import Path


def test_deploy_accepts_runtime_uid_owned_writable_directory_before_mutation() -> None:
    deploy_script = (Path(__file__).parents[1] / "scripts" / "deploy.sh").read_text()

    owner_check = deploy_script.index('existing_owner_uid="$(stat -c')
    acl_mutation = deploy_script.index("if command -v setfacl", owner_check)

    assert owner_check < acl_mutation
    assert '[[ "${existing_owner_uid}" == "10001" ]]' in deploy_script
    assert "(( (owner_permissions & 3) == 3 ))" in deploy_script
