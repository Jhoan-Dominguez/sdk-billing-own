"""Pobla la base de DESARROLLO con usuarios y 12 meses de compras ficticias.

Los usuarios coinciden con los del realm de Keycloak (infra/docker/keycloak/realm-compras.json):
mismos ids (`sub`), así que al iniciar sesión cada uno ve sus compras.

    .venv/bin/python scripts/seed_dev_data.py            # en local (Postgres del compose)
    docker compose exec app python scripts/seed_dev_data.py
    ... --reset                                          # borra y vuelve a generar sus compras

Es determinista (semilla fija): el mismo día genera los mismos datos.
"""

import argparse
import random
import sys
from dataclasses import dataclass, field
from datetime import date

from compras import bootstrap
from compras.application import purchases as purchase_service
from compras.application import users as user_service
from compras.domain.auth import ADMIN, CLIENTE
from compras.domain.periods import last_months, month_bounds

# --- Catálogo: comercios, rango de importe y productos típicos por categoría -------

CATALOG: dict[str, tuple[list[str], tuple[float, float], list[tuple[str, float]]]] = {
    "Supermercado": (
        ["Supermercado La Colonia", "Walmart", "PriceSmart", "Mercado Central", "Super Selectos"],
        (25, 140),
        [
            ("Leche entera 1L", 1.2),
            ("Pan integral", 2.5),
            ("Huevos x30", 6.8),
            ("Arroz 2kg", 3.4),
            ("Pollo 1kg", 5.9),
            ("Frutas variadas", 8.5),
            ("Detergente", 7.2),
            ("Café 500g", 9.0),
        ],
    ),
    "Restaurantes": (
        ["Pollo Campero", "Café Barista", "Pizza Hut", "Sushi Itto", "La Pampa Argentina"],
        (8, 65),
        [("Menú del día", 9.5), ("Bebida", 2.5), ("Postre", 4.0), ("Café americano", 2.2)],
    ),
    "Servicios": (
        ["Compañía de Luz", "Agua Potable", "Claro Internet", "Tigo Móvil", "Netflix"],
        (12, 95),
        [],
    ),
    "Transporte": (["Gasolinera Puma", "Uber", "Texaco", "Parqueo Central", "Bus Interurbano"], (3, 60), []),
    "Salud": (
        ["Farmacia San Nicolás", "Farmacia Económica", "Laboratorio Clínico", "Clínica Dental Sonrisa"],
        (6, 120),
        [("Ibuprofeno 400mg", 4.5), ("Vitamina C", 7.8), ("Consulta médica", 35), ("Examen de sangre", 22)],
    ),
    "Hogar": (
        ["Ferretería El Martillo", "Siman Hogar", "IKEA", "Vidrí"],
        (10, 180),
        [("Bombillo LED", 3.2), ("Juego de toallas", 18), ("Organizador", 12.5), ("Pintura 1 galón", 24)],
    ),
    "Tecnología": (
        ["Tienda Apple", "Office Depot", "Amazon", "Radioshack"],
        (15, 650),
        [
            ("Cable USB-C", 12),
            ("Audífonos", 45),
            ("Mouse inalámbrico", 25),
            ("Teclado", 60),
            ("Memoria USB 64GB", 14),
        ],
    ),
    "Educación": (
        ["Librería Cervantes", "Coursera", "Universidad Nacional", "Platzi"],
        (10, 220),
        [("Cuaderno", 3.5), ("Libro de texto", 38), ("Curso online", 29), ("Calculadora", 22)],
    ),
    "Entretenimiento": (["Cinépolis", "Spotify", "Steam", "Teatro Nacional"], (5, 80), []),
    "Otros": (["Correos", "Tienda de regalos", "Floristería"], (5, 50), []),
}

# Compras en euros (viaje de Sofía): comercio, categoría, rango.
TRIP = [
    ("Hotel Gran Vía", "Hogar", (90, 160)),
    ("Renfe", "Transporte", (20, 75)),
    ("Museo del Prado", "Entretenimiento", (15, 30)),
    ("Café de Oriente", "Restaurantes", (12, 55)),
    ("El Corte Inglés", "Otros", (25, 140)),
]

PAYMENT_METHODS = ["Tarjeta de crédito", "Tarjeta de débito", "Efectivo", "Transferencia"]


@dataclass
class Profile:
    user_id: str
    email: str
    name: str
    role: str
    categories: dict[str, int]  # peso relativo de cada categoría
    per_month: tuple[int, int]  # compras por mes (mín, máx)
    scale: float = 1.0  # multiplicador de importes
    growth: float = 0.0  # crecimiento mensual del gasto (0.04 = +4 %/mes)
    payments: list[int] = field(default_factory=lambda: [4, 3, 2, 1])  # pesos de PAYMENT_METHODS
    trip_months: tuple[int, ...] = ()  # índices (0 = hace 11 meses) con compras en EUR


# Ids = `id` de cada usuario en el realm de Keycloak (claim `sub`).
PROFILES = [
    Profile(
        "8f1c2a3e-0000-4000-8000-000000000001",
        "admin@compras.example.com",
        "Administrador Compras",
        ADMIN,
        {"Servicios": 3, "Tecnología": 2, "Restaurantes": 1},
        (2, 4),
    ),
    Profile(  # familia: mucho supermercado, gasto estable
        "8f1c2a3e-0000-4000-8000-000000000101",
        "cliente@compras.example.com",
        "Carlos Mendoza",
        CLIENTE,
        {"Supermercado": 6, "Servicios": 3, "Hogar": 2, "Salud": 2, "Transporte": 2, "Restaurantes": 1},
        (10, 14),
        scale=1.0,
        payments=[2, 5, 3, 1],
    ),
    Profile(  # gasto alto: tecnología, restaurantes y ocio, casi todo con tarjeta de crédito
        "8f1c2a3e-0000-4000-8000-000000000102",
        "maria.lopez@compras.example.com",
        "María López",
        CLIENTE,
        {"Tecnología": 3, "Restaurantes": 4, "Entretenimiento": 3, "Supermercado": 2, "Transporte": 2},
        (9, 13),
        scale=1.7,
        payments=[8, 2, 1, 1],
    ),
    Profile(  # estudiante: poco gasto pero en aumento, educación y transporte
        "8f1c2a3e-0000-4000-8000-000000000103",
        "juan.perez@compras.example.com",
        "Juan Pérez",
        CLIENTE,
        {"Educación": 4, "Transporte": 4, "Restaurantes": 2, "Entretenimiento": 2, "Supermercado": 1},
        (5, 9),
        scale=0.5,
        growth=0.06,
        payments=[1, 4, 5, 1],
    ),
    Profile(  # salud y hogar; viaje a España pagado en euros
        "8f1c2a3e-0000-4000-8000-000000000104",
        "sofia.ramirez@compras.example.com",
        "Sofía Ramírez",
        CLIENTE,
        {"Salud": 4, "Hogar": 4, "Supermercado": 3, "Servicios": 2, "Otros": 1},
        (7, 11),
        scale=1.2,
        payments=[3, 3, 1, 3],
        trip_months=(6, 7),
    ),
]


def money(x: float) -> float:
    return round(x, 2)


def random_day(rng: random.Random, month: str, today: date) -> date:
    start, end = month_bounds(month)
    days = (end - start).days
    if (start.year, start.month) == (today.year, today.month):
        days = today.day  # nada en el futuro
    return start.replace(day=rng.randint(1, days))


def purchase_for(rng: random.Random, p: Profile, month: str, index: int, today: date) -> tuple[dict, list[dict]]:
    category = rng.choices(list(p.categories), weights=list(p.categories.values()))[0]
    vendors, (low, high), products = CATALOG[category]
    factor = p.scale * (1 + p.growth) ** index * (1.35 if month.endswith("-12") else 1)
    values = {
        "purchase_date": random_day(rng, month, today),
        "vendor": rng.choice(vendors),
        "category": category,
        "currency": "USD",
        "payment_method": rng.choices(PAYMENT_METHODS, weights=p.payments)[0],
        "invoice_number": f"F-{rng.randint(1, 9):03d}-{rng.randint(1, 999999):06d}" if rng.random() < 0.6 else None,
    }
    items: list[dict] = []
    if products and rng.random() < 0.45:  # con detalle: el total se calcula de las líneas
        for name, base in rng.sample(products, k=rng.randint(1, min(4, len(products)))):
            items.append(
                {
                    "description": name,
                    "quantity": rng.randint(1, 3),
                    "unit_price": money(base * factor * rng.uniform(0.9, 1.2)),
                }
            )
    else:
        total = money(rng.uniform(low, high) * factor)
        if rng.random() < 0.5:  # con IVA desglosado (13 %)
            values["subtotal"] = money(total / 1.13)
            values["tax"] = money(total - values["subtotal"])
        values["total"] = total
    return values, items


def trip_purchase(rng: random.Random, month: str, today: date) -> tuple[dict, list[dict]]:
    vendor, category, (low, high) = rng.choice(TRIP)
    return {
        "purchase_date": random_day(rng, month, today),
        "vendor": vendor,
        "category": category,
        "currency": "EUR",
        "payment_method": "Tarjeta de crédito",
        "total": money(rng.uniform(low, high)),
        "notes": "Viaje a Madrid",
    }, []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reset", action="store_true", help="borra las compras de estos usuarios y regenera")
    args = parser.parse_args()

    bootstrap.init_database()
    storage = bootstrap.file_storage()
    today = date.today()
    months = last_months(12, today)
    rng = random.Random(2026)
    ids = [p.user_id for p in PROFILES]

    with bootstrap.unit_of_work() as uow:
        existing = [purchase for uid in ids for purchase in uow.purchases.by_owner(uid)]
        if existing and not args.reset:
            print(f"Ya hay {len(existing)} compras de los usuarios de prueba. Usa --reset para regenerarlas.")
            return 1
        for purchase in existing:
            purchase_service.delete(uow, storage, purchase)  # también borra sus archivos

        for p in PROFILES:
            first, _, last = p.name.partition(" ")
            user_service.sync_from_claims(
                uow,
                {
                    "sub": p.user_id,
                    "preferred_username": p.email,
                    "email": p.email,
                    "name": p.name,
                    "given_name": first,
                    "family_name": last,
                },
                p.role,
            )
            count = 0
            for index, month in enumerate(months):
                batch = [purchase_for(rng, p, month, index, today) for _ in range(rng.randint(*p.per_month))]
                if index in p.trip_months:
                    batch += [trip_purchase(rng, month, today) for _ in range(rng.randint(4, 7))]
                for values, items in batch:
                    purchase_service.create(uow, values, items, owner_id=p.user_id)
                    count += 1
            print(f"{p.name:<22} {p.role:<8} {count:>4} compras")
    return 0


if __name__ == "__main__":
    sys.exit(main())
