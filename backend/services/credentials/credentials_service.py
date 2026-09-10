"""Encrypted credential storage and SSH key management.

Secret material lives either in the local Postgres columns (Fernet-encrypted,
the default) or in OpenBao ("vault" storage backend). The ``storage_backend``
dispatch is contained entirely in this service — the three resolver seams
(``workflow_steps.common.credential_resolver``,
``services.credentials.source_credentials``, ``services.git.auth``) and every
ad-hoc reader go through the same ``get_decrypted_*`` / ``get_ssh_key_path``
methods and become vault-aware for free. See ``doc/VAULT_INTEGRATION.md``.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.orm import Session

from core.config import settings
from core.crypto import EncryptionService, resolve_credential_secret
from core.models.credentials import Credential
from repositories.credentials_repository import CredentialsRepository
from services.credentials.exceptions import (
    CredentialMissingFieldError,
    CredentialNameConflictError,
    CredentialNotFoundError,
    CredentialStorageBackendChangeError,
    CredentialVaultNotConfiguredError,
    CredentialVaultUnavailableError,
)
from services.vault.exceptions import VaultError, VaultSecretNotFoundError

logger = logging.getLogger(__name__)


class CredentialsService:
    def __init__(
        self,
        db: Session,
        *,
        vault_reader: Any | None = None,
        vault_writer: Any | None = None,
    ) -> None:
        self._repo = CredentialsRepository(db)
        secret = resolve_credential_secret(
            settings.credential_encryption_key or settings.secret_key
        )
        self._encryption = EncryptionService(secret)
        # `vault_reader` is resolved lazily (only when a vault-backed row is
        # touched) so local-only call sites and unit tests never import
        # service_factory. `vault_writer` is injected only by routers/credentials.py.
        self._vault_reader = vault_reader
        self._vault_reader_resolved = vault_reader is not None
        self._vault_writer = vault_writer

    # --------------------------------------------------------------- vault access
    def _get_vault_reader(self) -> Any | None:
        if not self._vault_reader_resolved:
            try:
                import service_factory

                self._vault_reader = service_factory.get_vault_service()
            except Exception:  # pragma: no cover - defensive
                self._vault_reader = None
            self._vault_reader_resolved = True
        return self._vault_reader

    def _read_vault_data(self, credential: Credential) -> dict[str, Any]:
        reader = self._get_vault_reader()
        if reader is None:
            raise CredentialVaultNotConfiguredError()
        if not credential.vault_path:
            raise CredentialMissingFieldError("Vault credential has no path")
        try:
            return reader.read_kv(credential.vault_path)
        except VaultError as exc:
            raise CredentialVaultUnavailableError(str(exc)) from exc

    @staticmethod
    def _build_vault_payload(
        cred_type: str,
        password: str | None,
        ssh_private_key: str | None,
        ssh_passphrase: str | None,
    ) -> dict[str, str]:
        payload: dict[str, str] = {}
        if cred_type == "ssh_key":
            if ssh_private_key:
                payload["ssh_key"] = ssh_private_key
            if ssh_passphrase:
                payload["ssh_passphrase"] = ssh_passphrase
        elif cred_type == "token":
            if password:
                payload["token"] = password
        elif password:
            payload["password"] = password
        return payload

    @staticmethod
    def _derive_vault_path(name: str, cred_id: int) -> str:
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
        return f"credentials/{safe_name}-{cred_id}"

    # ---------------------------------------------------------------------- reads
    def list_credentials(
        self,
        *,
        include_expired: bool = False,
        source: str | None = "general",
        acting_user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        rows = self._repo.list_visible(acting_user_id=acting_user_id, source=source)
        items = [
            self._to_dict(credential, owner_username=owner_username)
            for credential, owner_username in rows
        ]
        if not include_expired:
            items = [item for item in items if item["status"] != "expired"]
        return items

    def get_credential_by_id(
        self, cred_id: int, *, acting_user_id: int | None = None
    ) -> dict[str, Any] | None:
        credential = self._repo.get_by_id_for_user(cred_id, acting_user_id=acting_user_id)
        if credential is None:
            return None
        owner_username = None
        if credential.visibility == "private":
            found = self._repo.get_by_id_with_owner(cred_id)
            owner_username = found[1] if found else None
        return self._to_dict(credential, owner_username=owner_username)

    # -------------------------------------------------------------------- create
    def create_credential(
        self,
        *,
        name: str,
        username: str,
        cred_type: str,
        password: str | None = None,
        valid_until: str | None = None,
        source: str = "general",
        visibility: str = "private",
        ssh_private_key: str | None = None,
        ssh_passphrase: str | None = None,
        algorithm: str | None = None,
        storage_backend: str = "local",
        acting_user_id: int | None = None,
    ) -> dict[str, Any]:
        owner_user_id: int | None = None
        if visibility == "private":
            if acting_user_id is None:
                raise CredentialMissingFieldError("A private credential requires an owning user")
            owner_user_id = acting_user_id
            if self._repo.find_private_conflict(name, source, owner_user_id):
                raise CredentialNameConflictError(name)
        else:
            if self._repo.find_global_conflict(name, source):
                raise CredentialNameConflictError(name)

        now = datetime.now(UTC)

        if storage_backend == "vault":
            return self._create_vault_credential(
                name=name,
                username=username,
                cred_type=cred_type,
                password=password,
                ssh_private_key=ssh_private_key,
                ssh_passphrase=ssh_passphrase,
                algorithm=algorithm,
                valid_until=valid_until,
                source=source,
                visibility=visibility,
                owner_user_id=owner_user_id,
                now=now,
            )

        credential = self._repo.create(
            name=name,
            username=username,
            type=cred_type,
            algorithm=algorithm,
            password_encrypted=self._encryption.encrypt(password) if password else None,
            ssh_key_encrypted=self._encryption.encrypt(ssh_private_key)
            if ssh_private_key
            else None,
            ssh_passphrase_encrypted=self._encryption.encrypt(ssh_passphrase)
            if ssh_passphrase
            else None,
            valid_until=valid_until,
            source=source,
            visibility=visibility,
            owner_user_id=owner_user_id,
            is_active=True,
            created_at=now,
            updated_at=now,
            storage_backend="local",
        )
        if cred_type == "ssh_key" and ssh_private_key:
            self.export_single_ssh_key(credential.id, acting_user_id=acting_user_id)
        return self._to_dict(credential)

    def _create_vault_credential(
        self,
        *,
        name: str,
        username: str,
        cred_type: str,
        password: str | None,
        ssh_private_key: str | None,
        ssh_passphrase: str | None,
        algorithm: str | None,
        valid_until: str | None,
        source: str,
        visibility: str,
        owner_user_id: int | None,
        now: datetime,
    ) -> dict[str, Any]:
        if self._vault_writer is None:
            raise CredentialVaultNotConfiguredError()
        payload = self._build_vault_payload(cred_type, password, ssh_private_key, ssh_passphrase)
        if not payload:
            raise CredentialMissingFieldError("A vault credential requires a secret value")

        credential = self._repo.create_no_commit(
            name=name,
            username=username,
            type=cred_type,
            algorithm=algorithm,
            password_encrypted=None,
            ssh_key_encrypted=None,
            ssh_passphrase_encrypted=None,
            valid_until=valid_until,
            source=source,
            visibility=visibility,
            owner_user_id=owner_user_id,
            is_active=True,
            created_at=now,
            updated_at=now,
            storage_backend="vault",
            vault_path=None,
            vault_secret_fields=None,
        )
        vault_path = self._derive_vault_path(name, credential.id)
        try:
            self._vault_writer.write_kv(vault_path, payload)
        except VaultError as exc:
            self._repo.rollback()
            raise CredentialVaultUnavailableError(str(exc)) from exc
        except Exception:
            self._repo.rollback()
            raise

        self._repo.update_no_commit(
            credential,
            vault_path=vault_path,
            vault_secret_fields=",".join(sorted(payload)),
        )
        self._repo.commit()
        self._repo.refresh(credential)
        return self._to_dict(credential)

    # -------------------------------------------------------------------- update
    def update_credential(
        self,
        cred_id: int,
        *,
        name: str | None = None,
        username: str | None = None,
        cred_type: str | None = None,
        password: str | None = None,
        valid_until: str | None = None,
        visibility: str | None = None,
        ssh_private_key: str | None = None,
        ssh_passphrase: str | None = None,
        algorithm: str | None = None,
        storage_backend: str | None = None,
        acting_user_id: int | None = None,
    ) -> dict[str, Any]:
        credential = self._repo.get_by_id_for_user(cred_id, acting_user_id=acting_user_id)
        if credential is None:
            raise CredentialNotFoundError(cred_id)

        if storage_backend is not None and storage_backend != credential.storage_backend:
            raise CredentialStorageBackendChangeError()

        final_visibility = visibility if visibility is not None else credential.visibility
        final_name = name if name is not None else credential.name
        final_owner_user_id = credential.owner_user_id
        if visibility is not None and visibility != credential.visibility:
            final_owner_user_id = acting_user_id if visibility == "private" else None

        if name is not None or visibility is not None:
            if final_visibility == "private":
                if final_owner_user_id is None:
                    raise CredentialMissingFieldError(
                        "A private credential requires an owning user"
                    )
                conflict = self._repo.find_private_conflict(
                    final_name, credential.source, final_owner_user_id, exclude_id=cred_id
                )
            else:
                conflict = self._repo.find_global_conflict(
                    final_name, credential.source, exclude_id=cred_id
                )
            if conflict is not None:
                raise CredentialNameConflictError(final_name)

        updates: dict[str, Any] = {"updated_at": datetime.now(UTC)}
        if name is not None:
            updates["name"] = name
        if username is not None:
            updates["username"] = username
        if cred_type is not None:
            updates["type"] = cred_type
        if algorithm is not None:
            updates["algorithm"] = algorithm
        if valid_until is not None:
            updates["valid_until"] = valid_until
        if visibility is not None:
            updates["visibility"] = visibility
            updates["owner_user_id"] = final_owner_user_id

        secret_supplied = (
            password is not None or ssh_private_key is not None or ssh_passphrase is not None
        )
        final_type = cred_type if cred_type is not None else credential.type

        if credential.storage_backend == "vault":
            if secret_supplied:
                new_fields = self._build_vault_payload(
                    final_type, password, ssh_private_key, ssh_passphrase
                )
                merged = self._merge_vault_secret(credential, new_fields)
                updates["vault_secret_fields"] = ",".join(sorted(merged))
        else:
            if password is not None:
                updates["password_encrypted"] = self._encryption.encrypt(password)
            if ssh_private_key is not None:
                updates["ssh_key_encrypted"] = self._encryption.encrypt(ssh_private_key)
            if ssh_passphrase is not None:
                updates["ssh_passphrase_encrypted"] = self._encryption.encrypt(ssh_passphrase)

        updated = self._repo.update(credential, **updates)
        if (
            final_type == "ssh_key"
            and ssh_private_key is not None
            and credential.storage_backend != "vault"
        ):
            self.export_single_ssh_key(cred_id, acting_user_id=acting_user_id)
        return self._to_dict(updated)

    def _merge_vault_secret(
        self, credential: Credential, new_fields: dict[str, str]
    ) -> set[str]:
        if self._vault_writer is None:
            raise CredentialVaultNotConfiguredError()
        if not credential.vault_path:
            raise CredentialMissingFieldError("Vault credential has no path")
        try:
            existing = self._vault_writer.read_kv(credential.vault_path)
        except VaultSecretNotFoundError:
            existing = {}
        except VaultError as exc:
            raise CredentialVaultUnavailableError(str(exc)) from exc
        merged = {**existing, **new_fields}
        try:
            self._vault_writer.write_kv(credential.vault_path, merged)
        except VaultError as exc:
            raise CredentialVaultUnavailableError(str(exc)) from exc
        return set(merged)

    # -------------------------------------------------------------------- delete
    def delete_credential(self, cred_id: int, *, acting_user_id: int | None = None) -> None:
        credential = self._repo.get_by_id_for_user(cred_id, acting_user_id=acting_user_id)
        if credential is None:
            raise CredentialNotFoundError(cred_id)
        if credential.storage_backend == "vault" and credential.vault_path:
            if self._vault_writer is not None:
                try:
                    self._vault_writer.delete_kv(credential.vault_path)
                except VaultError:
                    logger.warning(
                        "Failed to delete OpenBao secret for credential %s at %s; "
                        "removing the database row anyway",
                        cred_id,
                        credential.vault_path,
                        exc_info=True,
                    )
        elif credential.type == "ssh_key":
            self._delete_ssh_key_file(
                credential.name, credential.visibility, credential.owner_user_id
            )
        self._repo.delete(credential)

    # ------------------------------------------------------------ decrypted reads
    def get_decrypted_password(self, cred_id: int, *, acting_user_id: int | None = None) -> str:
        credential = self._repo.get_by_id_for_user(cred_id, acting_user_id=acting_user_id)
        if credential is None:
            raise CredentialNotFoundError(cred_id)
        if credential.storage_backend == "vault":
            data = self._read_vault_data(credential)
            value = data.get("password") or data.get("token")
            if not value:
                raise CredentialMissingFieldError("Credential has no password")
            return value
        if not credential.password_encrypted:
            raise CredentialMissingFieldError("Credential has no password")
        return self._encryption.decrypt(credential.password_encrypted)

    def get_decrypted_ssh_key(self, cred_id: int, *, acting_user_id: int | None = None) -> str:
        credential = self._repo.get_by_id_for_user(cred_id, acting_user_id=acting_user_id)
        if credential is None:
            raise CredentialNotFoundError(cred_id)
        if credential.storage_backend == "vault":
            data = self._read_vault_data(credential)
            value = data.get("ssh_key")
            if not value:
                raise CredentialMissingFieldError("Credential has no SSH key")
            return value
        if not credential.ssh_key_encrypted:
            raise CredentialMissingFieldError("Credential has no SSH key")
        return self._encryption.decrypt(credential.ssh_key_encrypted)

    def get_decrypted_ssh_passphrase(
        self, cred_id: int, *, acting_user_id: int | None = None
    ) -> str | None:
        credential = self._repo.get_by_id_for_user(cred_id, acting_user_id=acting_user_id)
        if credential is None:
            raise CredentialNotFoundError(cred_id)
        if credential.storage_backend == "vault":
            data = self._read_vault_data(credential)
            return data.get("ssh_passphrase") or None
        if not credential.ssh_passphrase_encrypted:
            return None
        return self._encryption.decrypt(credential.ssh_passphrase_encrypted)

    def get_ssh_key_path(self, cred_id: int, *, acting_user_id: int | None = None) -> str | None:
        credential = self._repo.get_by_id_for_user(cred_id, acting_user_id=acting_user_id)
        if credential is None or credential.type != "ssh_key":
            return None
        if credential.storage_backend == "vault":
            data = self._read_vault_data(credential)
            key_material = data.get("ssh_key")
            if not key_material:
                raise CredentialMissingFieldError("Credential has no SSH key")
            return self._write_ssh_key_file(credential, key_material)
        if not credential.ssh_key_encrypted:
            return None
        output_dir = self._ssh_keys_directory()
        prefix = self._ssh_key_filename_prefix(credential.visibility, credential.owner_user_id)
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", credential.name)
        key_path = os.path.join(output_dir, f"{prefix}{safe_name}")
        if os.path.exists(key_path):
            return key_path
        return self.export_single_ssh_key(cred_id, acting_user_id=acting_user_id)

    def export_single_ssh_key(
        self, cred_id: int, *, acting_user_id: int | None = None
    ) -> str | None:
        credential = self._repo.get_by_id_for_user(cred_id, acting_user_id=acting_user_id)
        if credential is None:
            logger.warning("Credential with ID %s not found", cred_id)
            return None
        if credential.type != "ssh_key" or not credential.ssh_key_encrypted:
            return None
        try:
            ssh_key_content = self._encryption.decrypt(credential.ssh_key_encrypted)
            return self._write_ssh_key_file(credential, ssh_key_content)
        except Exception:
            logger.exception("Failed to export SSH key '%s'", credential.name)
            return None

    def _write_ssh_key_file(self, credential: Credential, contents: str) -> str:
        output_dir = self._ssh_keys_directory()
        os.makedirs(output_dir, exist_ok=True)
        prefix = self._ssh_key_filename_prefix(credential.visibility, credential.owner_user_id)
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", credential.name)
        key_filename = os.path.join(output_dir, f"{prefix}{safe_name}")
        with open(key_filename, "w", encoding="utf-8") as handle:
            handle.write(contents)
            if not contents.endswith("\n"):
                handle.write("\n")
        os.chmod(key_filename, 0o600)
        logger.info("Exported SSH key '%s' to %s", credential.name, key_filename)
        return key_filename

    def _ssh_keys_directory(self) -> str:
        return str(settings.data_directory / "ssh_keys")

    def _ssh_key_filename_prefix(self, visibility: str, owner_user_id: int | None) -> str:
        if visibility == "global":
            return "global_"
        if owner_user_id is not None:
            return f"user{owner_user_id}_"
        return "private_"

    def _delete_ssh_key_file(
        self,
        cred_name: str,
        visibility: str,
        owner_user_id: int | None,
    ) -> bool:
        output_dir = self._ssh_keys_directory()
        prefix = self._ssh_key_filename_prefix(visibility, owner_user_id)
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", cred_name)
        key_filename = os.path.join(output_dir, f"{prefix}{safe_name}")
        try:
            if os.path.exists(key_filename):
                os.remove(key_filename)
                logger.info("Deleted SSH key file: %s", key_filename)
                return True
            return False
        except Exception:
            logger.exception("Failed to delete SSH key file '%s'", key_filename)
            return False

    def _to_dict(
        self, credential: Credential, *, owner_username: str | None = None
    ) -> dict[str, Any]:
        status = "active"
        if credential.valid_until:
            try:
                expiry = datetime.fromisoformat(credential.valid_until).date()
                today = date.today()
                if expiry < today:
                    status = "expired"
                elif (expiry - today).days <= 7:
                    status = "expiring"
            except ValueError:
                status = "unknown"

        if credential.storage_backend == "vault":
            fields = {f for f in (credential.vault_secret_fields or "").split(",") if f}
            has_password = bool({"password", "token"} & fields)
            has_ssh_key = "ssh_key" in fields
            has_ssh_passphrase = "ssh_passphrase" in fields
        else:
            has_password = credential.password_encrypted is not None
            has_ssh_key = credential.ssh_key_encrypted is not None
            has_ssh_passphrase = credential.ssh_passphrase_encrypted is not None

        return {
            "id": credential.id,
            "name": credential.name,
            "username": credential.username,
            "type": credential.type,
            "algorithm": credential.algorithm,
            "valid_until": credential.valid_until,
            "is_active": credential.is_active,
            "source": credential.source,
            "owner": credential.owner,
            "owner_user_id": credential.owner_user_id,
            "owner_username": owner_username,
            "visibility": credential.visibility,
            "storage_backend": credential.storage_backend,
            "vault_path": credential.vault_path,
            "created_at": credential.created_at.isoformat() if credential.created_at else None,
            "updated_at": credential.updated_at.isoformat() if credential.updated_at else None,
            "status": status,
            "has_password": has_password,
            "has_ssh_key": has_ssh_key,
            "has_ssh_passphrase": has_ssh_passphrase,
        }
