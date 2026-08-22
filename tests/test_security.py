from app.security import decrypt_secret, encrypt_secret, mask_secret


def test_credentials_round_trip_and_masking() -> None:
    plaintext = "secret-value-123456"
    ciphertext = encrypt_secret(plaintext)
    assert ciphertext is not None
    assert ciphertext != plaintext
    assert decrypt_secret(ciphertext) == plaintext
    assert mask_secret(plaintext) == "secr...3456"
    assert plaintext not in mask_secret(plaintext)


def test_empty_credentials_are_not_stored() -> None:
    assert encrypt_secret(None) is None
    assert encrypt_secret("") is None
    assert mask_secret(None) is None
