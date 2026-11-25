from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

Modalidad = Literal["texto", "imagen", "video", "lidar"]
Geometria = Literal["span", "bbox", "poligono", "bbox_video", "cuboide_3d"]

GEOMETRIAS_POR_MODALIDAD: dict[str, set[str]] = {
    "texto": {"span"},
    "imagen": {"bbox", "poligono"},
    "video": {"bbox_video"},
    "lidar": {"cuboide_3d"},
}


def validar_claves(valor: Any) -> Any:
    """Rechaza claves que MongoDB interpretaría como operadores o rutas."""
    if isinstance(valor, dict):
        for clave, contenido in valor.items():
            if not isinstance(clave, str) or clave.startswith("$") or "." in clave:
                raise ValueError(f"clave no permitida: {clave!r}")
            validar_claves(contenido)
    elif isinstance(valor, list):
        for elemento in valor:
            validar_claves(elemento)
    return valor


class Etiqueta(BaseModel):
    etiqueta: str = Field(min_length=1, max_length=100)
    instruccion: str = Field(default="", max_length=500)


class ProyectoIn(BaseModel):
    cliente_id: str = Field(min_length=1)
    nombre: str = Field(min_length=1, max_length=200)
    taxonomia: list[Etiqueta] = Field(min_length=1)
    sla_horas: int = Field(default=48, gt=0)
    modalidad: Modalidad | None = None


class Archivo(BaseModel):
    uri: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(gt=0)
    mime: str = Field(min_length=1)
    meta: dict[str, Any] = Field(default_factory=dict)

    @field_validator("meta")
    @classmethod
    def validar_meta(cls, valor):
        return validar_claves(valor)


class TareaIn(BaseModel):
    archivo: Archivo
    modalidad: Modalidad
    tipo_tarea: Geometria
    prioridad: int = Field(default=3, ge=1, le=5)

    @model_validator(mode="after")
    def geometria_compatible(self):
        if self.tipo_tarea not in GEOMETRIAS_POR_MODALIDAD[self.modalidad]:
            raise ValueError(f"{self.tipo_tarea} no corresponde a la modalidad {self.modalidad}")
        return self


class LoteIn(BaseModel):
    tareas: list[TareaIn] = Field(min_length=1, max_length=5000)


class Anotacion(BaseModel):
    etiqueta: str = Field(min_length=1)
    geometria: dict[str, Any]

    @field_validator("geometria")
    @classmethod
    def validar_geometria(cls, valor):
        return validar_claves(valor)


class TransicionIn(BaseModel):
    tipo: Literal["asignar", "enviar", "liberar", "iniciar_revision", "aprobar", "rechazar"]
    event_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    anotador_id: str | None = None
    token: str | None = None
    token_anterior: str | None = None
    anotacion: Anotacion | None = None
    revisor_id: str | None = None
    motivo: str | None = None

    @model_validator(mode="after")
    def campos_requeridos(self):
        requeridos = {
            "asignar": ("anotador_id", "token"),
            "enviar": ("anotador_id", "token", "anotacion"),
            "liberar": ("anotador_id", "token"),
            "iniciar_revision": ("revisor_id",),
            "aprobar": ("revisor_id",),
            "rechazar": ("revisor_id", "motivo"),
        }[self.tipo]
        faltantes = [campo for campo in requeridos if getattr(self, campo) is None]
        if faltantes:
            raise ValueError(f"faltan campos para {self.tipo}: {', '.join(faltantes)}")
        return self
