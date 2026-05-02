from __future__ import annotations

from django.contrib.auth.hashers import Argon2PasswordHasher


class UserCodeArgon2Hasher(Argon2PasswordHasher):
    """
    Lower-cost Argon2 hasher for UserCode PINs.

    Alarm PINs are 4-8 digits with a 10K-100M keyspace. Stretching them with
    the default user-password Argon2 cost (~150-300ms/verify) doesn't
    materially raise an offline-brute-force attacker's cost: the keyspace is
    so small that the entire space is recovered in minutes-to-hours even at
    strong cost, while the slow verify shows up as a multi-hundred-ms tax on
    every arm/disarm round trip through the MQTT alarm panel.

    Calibrated for ~30ms/verify - plenty for the online-rate-limited entry
    path while letting clicks feel instant. The algorithm discriminator is
    renamed so check_password routes new and old UserCode hashes to the right
    hasher: existing rows hashed under the default 'argon2' algorithm continue
    to verify on the strong hasher with no migration required.

    Strong-cost protection for User passwords (long, high-entropy, large
    keyspace) is unchanged - this hasher is only routed through explicit
    `make_password(..., hasher='argon2-pin')` calls in `accounts.use_cases.user_codes`.
    """

    algorithm = "argon2-pin"
    time_cost = 1
    memory_cost = 8 * 1024
    parallelism = 2
