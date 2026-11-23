import valkey

from .config import VALKEY_HOST, VALKEY_PORT, VALKEY_TIMEOUT_S

cliente = valkey.Valkey(
    host=VALKEY_HOST,
    port=VALKEY_PORT,
    decode_responses=True,
    socket_timeout=VALKEY_TIMEOUT_S,
    socket_connect_timeout=VALKEY_TIMEOUT_S,
)


def llave_lock(tarea_id: str) -> str:
    return f"lock:tarea:{tarea_id}"


def llave_sesion(anotador_id: str) -> str:
    return f"sesion:{anotador_id}"


def llave_borrador(tarea_id: str) -> str:
    return f"borrador:{tarea_id}"


def llave_editando(proyecto_id: str) -> str:
    return f"editando:{proyecto_id}"


def llave_envio(tarea_id: str) -> str:
    return f"envio:{tarea_id}"


# KEYS: lock, borrador, sesion, editando, envio
# ARGV: token, limpiar (1/0), tarea_id, anotador_id
LIBERAR = cliente.register_script(
    """
    if redis.call('GET', KEYS[1]) ~= ARGV[1] then
        return 0
    end
    redis.call('DEL', KEYS[1])
    if ARGV[2] == '1' then
        redis.call('DEL', KEYS[2], KEYS[5])
        if redis.call('HGET', KEYS[3], 'tarea_id') == ARGV[3] then
            redis.call('DEL', KEYS[3])
        end
        redis.call('ZREM', KEYS[4], ARGV[4])
    end
    return 1
    """
)

# KEYS: lock, borrador, editando, envio
# ARGV: token, ttl_ms, contenido, ts_ms, anotador_id, limite_ms, envio
# Con `envio` no vacío se guarda el envío pendiente (ADR-007); si no, el borrador.
GUARDAR_BORRADOR = cliente.register_script(
    """
    if redis.call('GET', KEYS[1]) ~= ARGV[1] then
        return 0
    end
    redis.call('PEXPIRE', KEYS[1], ARGV[2])
    if ARGV[7] ~= '' then
        redis.call('HSET', KEYS[4], 'datos', ARGV[7], 'ts', ARGV[4], 'anotador_id', ARGV[5], 'token', ARGV[1])
    else
        redis.call('HSET', KEYS[2], 'contenido', ARGV[3], 'ts', ARGV[4], 'anotador_id', ARGV[5])
    end
    redis.call('ZADD', KEYS[3], ARGV[4], ARGV[5])
    redis.call('ZREMRANGEBYSCORE', KEYS[3], '-inf', ARGV[6])
    return 1
    """
)
