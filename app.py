from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import List

from flask import Flask, jsonify, request, render_template_string, Response

app = Flask(__name__)

# =========================
# Configuración básica
# =========================
BRAND_NAME = os.getenv("BRAND_NAME", "Nivora")
PRIMARY_COLOR = os.getenv("PRIMARY_COLOR", "#0f172a")
SECONDARY_COLOR = os.getenv("SECONDARY_COLOR", "#06b6d4")
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "hola@nivora.ai")
INSTAGRAM_URL = os.getenv("INSTAGRAM_URL", "https://instagram.com/nivora.ai")
WHATSAPP_NUMBER = os.getenv("WHATSAPP_NUMBER", "")


@dataclass
class FAQ:
    key: str
    title: str
    answer: str
    keywords: List[str]
    follow_ups: List[str] = field(default_factory=list)


FAQS: List[FAQ] = [
    FAQ(
        key="envio_simple",
        title="¿Cuánto tarda la implementación?",
        answer=(
            "La implementación suele tardar entre 24 y 72 horas 👍\n\n"
            "Depende del plan elegido y de la complejidad de tu tienda, pero la idea es dejarlo funcionando lo antes posible para que puedas empezar a usarlo sin demoras.\n\n"
            "Si querés, también podés ver qué plan se adapta mejor a tu tienda en la pestaña Precios."
        ),
        keywords=["cuanto tarda", "cuánto tarda", "cuanto demora", "cuánto demora", "en cuanto tiempo esta", "en cuánto tiempo está", "implementacion", "activacion", "integracion"],
        follow_ups=["Precios"],
    ),
    FAQ(
        key="stock_simple",
        title="¿Está disponible para mi tienda?",
        answer=(
            "Sí, Nivora se puede implementar sin problema 👍\n\n"
            "La idea es adaptarlo a tu tienda para que empiece a responder con criterio y te ayude a vender mejor.\n\n"
            "Si querés, te contamos cuál encaja mejor según tu caso."
        ),
        keywords=["tenes stock", "tenés stock", "hay stock", "stock", "disponible", "esta disponible", "está disponible", "lo puedo implementar"],
        follow_ups=["¿Cómo funciona en una tienda?"],
    ),
    FAQ(
        key="uso_simple",
        title="¿Cómo funciona?",
        answer=(
            "Funciona como un asistente que responde dudas reales de tus clientes dentro de tu tienda 😊\n\n"
            "La idea es acompañar la compra, resolver objeciones en el momento y hacer que más personas avancen sin depender de atención manual."
        ),
        keywords=["como se usa", "cómo se usa", "uso", "como funciona", "cómo funciona", "funcionamiento"],
        follow_ups=["¿Qué tipo de preguntas responde?"],
    ),
    FAQ(
        key="cambios_simple",
        title="¿Qué tipo de dudas puede resolver?",
        answer=(
            "Puede resolver dudas frecuentes como implementación, planes, integración, personalización y consultas comunes que hoy suelen frenar la decisión 👍\n\n"
            "La idea es sacar fricción en el momento justo para que la conversación avance y no se pierdan oportunidades."
        ),
        keywords=["dudas frecuentes", "que dudas resuelve", "qué dudas resuelve", "que consultas resuelve", "qué consultas resuelve"],
        follow_ups=["¿Qué tipo de preguntas responde?"],
    ),
    FAQ(
        key="caso_simple",
        title="¿Sirve para mi caso?",
        answer=(
            "Depende del caso, pero en la mayoría de situaciones funciona muy bien 😊\n\n"
            "Si querés, contame un poco más y te oriento mejor."
        ),
        keywords=["sirve para mi caso", "sirve para mi", "sirve para este caso", "me sirve", "sirve"],
        follow_ups=["¿Qué tipo de preguntas responde?"],
    ),
    FAQ(
        key="funcionamiento",
        title="¿Cómo funciona en una tienda?",
        answer=(
            "Funciona de forma muy simple.\n\n"
            "La persona entra a tu tienda, hace una pregunta desde el chat y el asistente responde al instante con información de tus productos, envíos, cambios, medios de pago o dudas frecuentes.\n\n"
            "Eso ayuda a sacar fricción justo en el momento en que la venta todavía se está decidiendo.\n\n"
            "Si querés, también puedo mostrarte qué tipo de preguntas responde en una tienda real."
        ),
        keywords=["como funciona", "como funciona en una tienda", "cómo funciona", "funciona en una tienda", "como trabaja", "como responde"],
        follow_ups=["¿Qué tipo de preguntas responde?", "¿Qué beneficios tiene?"],
    ),
    FAQ(
        key="preguntas",
        title="¿Qué tipo de preguntas responde?",
        answer=(
            "Puedo responder dudas comunes de clientes como tiempos de implementación, precios, funcionamiento, integración, personalización del bot y preguntas frecuentes que ayudan a decidir mejor.\n\n"
            "La idea es acompañar la compra, resolver objeciones en el momento y hacer que más personas avancen sin necesitar atención manual.\n\n"
            "Si querés, también puedo mostrarte cómo se adapta a tu tipo de tienda."
        ),
        keywords=["que tipo de preguntas responde", "qué tipo de preguntas responde", "que puede responder", "qué puede responder", "que tipo de dudas responde", "qué dudas responde", "que consultas responde", "qué consultas responde", "preguntas frecuentes", "faq", "responde preguntas"],
        follow_ups=["¿Se puede adaptar a mi negocio?"],
    ),
    FAQ(
        key="shopify",
        title="¿Se instala en Shopify?",
        answer=(
            "Sí, se puede instalar en Shopify sin problema.\n\n"
            "De hecho, es uno de los escenarios más comunes para Nivora porque muchas tiendas necesitan responder rápido sin depender del celular o del equipo de soporte.\n\n"
            "La implementación está pensada para que sea simple, ordenada y acompañada de principio a fin."
        ),
        keywords=["shopify", "se instala en shopify", "sirve para shopify", "funciona con shopify", "tienda shopify"],
        follow_ups=["¿Tengo que saber programar?", "¿Es difícil de instalar?"],
    ),
    FAQ(
        key="instalacion",
        title="¿Es difícil de instalar?",
        answer=(
            "No, la idea es justamente lo contrario: que sea simple.\n\n"
            "Nivora se integra rápido sobre tu tienda actual, sin que tengas que desarrollar un sistema aparte ni ocuparte de lo técnico.\n\n"
            "Además, la configuración inicial se adapta a tu negocio para que el asistente ya salga respondiendo con criterio desde el comienzo."
        ),
        keywords=["instalacion", "instalación", "es dificil de instalar", "es dificil", "cuanto tarda instalar", "implementacion", "implementación"],
        follow_ups=["¿Tengo que saber programar?", "¿Funciona con mi tienda?"],
    ),
    FAQ(
        key="tiempo_implementacion",
        title="¿Cuánto tarda la implementación?",
        answer=(
            "La implementación suele tardar entre 24 y 72 horas 👍\n\n"
            "Depende del plan elegido y de la complejidad de tu tienda, pero la idea es dejarlo funcionando lo antes posible para que puedas empezar a usarlo sin demoras.\n\n"
            "Si querés, también podés ver qué plan se adapta mejor a tu tienda en la pestaña Precios."
        ),
        keywords=[
            "cuanto tarda",
            "cuánto tarda",
            "cuanto demora",
            "cuánto demora",
            "en cuanto tiempo",
            "en cuánto tiempo",
            "cuando estaria",
            "cuándo estaría",
            "tiempo de implementacion",
            "tiempo de implementación",
            "tiempo de instalacion",
            "tiempo de instalación",
            "cuando estaria listo",
            "cuándo estaría listo",
        ],
        follow_ups=["¿Es difícil de instalar?", "¿Tengo que saber programar?"],
    ),
    FAQ(
        key="programar",
        title="¿Tengo que saber programar?",
        answer=(
            "No hace falta que sepas programar.\n\n"
            "Nosotros nos encargamos de dejar el asistente configurado e integrado según lo que necesite tu tienda.\n\n"
            "Además, si más adelante querés ajustar respuestas, tono o preguntas frecuentes, también se puede ir adaptando."
        ),
        keywords=["no se programar", "no sé programar", "tengo que saber programar", "programar", "codigo", "código", "tecnico", "técnico"],
        follow_ups=["¿Es difícil de instalar?", "¿Se instala en Shopify?"],
    ),
    FAQ(
        key="adaptacion",
        title="¿Se puede adaptar a mi negocio?",
        answer=(
            "Sí, se puede adaptar a todo tipo de tiendas 👍\n\n"
            "El asistente se configura según tu tipo de producto, tu forma de vender y las consultas reales que recibís.\n\n"
            "La idea es que se sienta útil, claro y alineado con tu negocio desde el primer día."
        ),
        keywords=["se puede adaptar", "adaptar a mi negocio", "mi negocio", "personalizar", "personalizado", "custom", "customizar", "marca", "tono"],
        follow_ups=["¿Qué beneficios tiene?", "¿Qué pasa si quiero cambiar respuestas después?"],
    ),
    FAQ(
        key="personalizacion_tono",
        title="¿Se puede personalizar cómo responde el bot?",
        answer=(
            "Sí, totalmente 👍\n\n"
            "El bot se adapta al estilo de tu tienda: más formal, más cercano o más vendedor, según lo que necesites.\n\n"
            "La idea es que acompañe a tus clientes y los ayude a decidir, manteniendo tu forma de comunicar."
        ),
        keywords=["tono", "personalidad", "forma de responder", "mas amable", "más amable", "adaptar", "personalizado", "personalizar", "como responde", "cómo responde"],
        follow_ups=["¿Se puede adaptar a mi negocio?", "¿Qué tipo de preguntas responde?"],
    ),
    FAQ(
        key="beneficios",
        title="¿Qué beneficios tiene?",
        answer=(
            "Los beneficios más claros suelen ser estos:\n\n"
            "• responde consultas al instante\n"
            "• reduce fricción antes de decidir\n"
            "• baja la carga manual del equipo\n"
            "• acompaña mejor al cliente\n"
            "• ayuda a recuperar ventas que hoy se pierden por no responder a tiempo\n\n"
            "En resumen: más claridad para quien evalúa comprar y menos esfuerzo para tu negocio 👍"
        ),
        keywords=["beneficios", "ventajas", "para que sirve", "para qué sirve", "que gano", "qué gano", "vale la pena", "retorno"],
        follow_ups=["¿Vale la pena?", "¿Se puede adaptar a mi negocio?"],
    ),
    FAQ(
        key="cambios",
        title="¿Qué pasa si quiero cambiar respuestas después?",
        answer=(
            "Se puede ajustar sin problema.\n\n"
            "Si querés cambiar respuestas, sumar información nueva, actualizar políticas o adaptar el tono, el sistema se puede ir mejorando con el tiempo.\n\n"
            "La idea no es dejarte un bot rígido, sino una solución que acompañe cómo evoluciona tu tienda."
        ),
        keywords=["cambiar respuestas", "editar respuestas", "modificar respuestas", "actualizar respuestas", "cambiar despues", "cambiar después"],
        follow_ups=["¿Se puede adaptar a mi negocio?", "¿Tengo soporte?"],
    ),
    FAQ(
        key="otras_plataformas",
        title="¿Solo sirve para Shopify?",
        answer=(
            "No. Shopify es un caso muy común, pero Nivora no se limita a una sola plataforma.\n\n"
            "Si ya tenés una tienda funcionando, en la mayoría de los casos se puede evaluar cómo integrarlo sin volver complejo el proceso.\n\n"
            "Si querés, puedo orientarte para ver si aplica bien a tu caso."
        ),
        keywords=["solo shopify", "solo sirve para shopify", "otra plataforma", "woocommerce", "tienda nube", "tiendanube", "solo funciona en shopify"],
        follow_ups=["¿Funciona con mi tienda?", "Hablar por WhatsApp"],
    ),
    FAQ(
        key="sirve_para_mi_tienda",
        title="¿Sirve para mi tienda?",
        answer=(
            "Sí, se puede adaptar a todo tipo de tiendas 👍\n\n"
            "Se configura según lo que vendés, cómo atendés y las dudas reales que suelen aparecer antes de comprar.\n\n"
            "La idea es que se sienta natural para tu marca y útil para tus clientes."
        ),
        keywords=["sirve para mi tienda", "sirve para mi ecommerce", "me sirve", "aplica para mi tienda", "funciona con mi tienda"],
        follow_ups=["¿Qué beneficios tiene?", "¿Es difícil de instalar?"],
    ),
    FAQ(
        key="precio",
        title="¿Cuánto cuesta?",
        answer=(
            "El valor depende del nivel de personalización que necesite tu tienda.\n\n"
            "Trabajamos con planes simples que se adaptan a cada negocio.\n\n"
            "Además, ofrecemos una garantía de 7 días: si dentro de ese período no te resulta útil, podés solicitar la devolución.\n\n"
            "Si querés, podemos orientarte con la opción más adecuada según tu caso."
        ),
        keywords=["precio", "cual es el precio", "cuál es el precio", "cuanto cuesta", "cuánto cuesta", "cuanto sale", "cuánto sale", "cuanto vale", "cuánto vale", "plan", "planes", "costo", "costos", "mensual", "valor", "inversion", "inversión", "sale"],
        follow_ups=["¿Tiene garantía?", "Hablar por WhatsApp"],
    ),
    FAQ(
        key="ia",
        title="¿Es como ChatGPT?",
        answer=(
            "No exactamente.\n\n"
            "Aunque utiliza lógica similar, este asistente está pensado específicamente para tu negocio.\n\n"
            "No responde de forma genérica, sino que se configura con información real de tu tienda para responder de manera clara, coherente y útil para tus clientes.\n\n"
            "La idea es que funcione como un asistente de atención, no como una IA abierta."
        ),
        keywords=["es como chatgpt", "es ia", "es inteligencia artificial", "funciona como una ia", "funciona como una inteligencia artificial", "chatgpt"],
        follow_ups=["¿Se puede adaptar a mi negocio?", "¿Qué tipo de preguntas responde?"],
    ),
    FAQ(
        key="garantia",
        title="¿Tiene garantía?",
        answer=(
            "Sí, ofrecemos una garantía de 7 días.\n\n"
            "Si dentro de ese período sentís que no te aporta valor, podés solicitar la devolución.\n\n"
            "La idea es que pruebes el sistema en tu tienda con tranquilidad."
        ),
        keywords=["garantia", "garantía", "tiene garantia", "tiene garantía", "y si no me sirve", "puedo cancelar", "riesgo", "sin riesgo", "devolucion", "devolución"],
        follow_ups=["¿Cuánto cuesta?", "Hablar por WhatsApp"],
    ),
    FAQ(
        key="vale_la_pena",
        title="¿Vale la pena?",
        answer=(
            "Sí, totalmente.\n\n"
            "Este tipo de asistente ayuda a responder consultas en el momento, acompaña al cliente durante la compra y evita que se pierdan ventas por falta de respuesta.\n\n"
            "Además, reduce la necesidad de estar pendiente del chat todo el tiempo o de contratar atención manual para preguntas repetidas.\n\n"
            "La idea es mejorar la experiencia del cliente y hacer más eficiente la atención sin agregar complejidad."
        ),
        keywords=["vale la pena", "conviene", "retorno", "roi", "sirve de verdad", "funciona de verdad"],
        follow_ups=["¿Qué beneficios tiene?", "Hablar por WhatsApp"],
    ),
    FAQ(
        key="demo",
        title="Quiero una demo",
        answer=(
            "Una demo ayuda mucho a visualizar cómo respondería el asistente en tu caso y qué tipo de consultas podría automatizar.\n\n"
            "Así podés imaginarlo dentro de tu tienda antes de tomar una decisión.\n\n"
            "Si querés, compartime tu duda principal y te muestro por dónde empezaría."
        ),
        keywords=["demo", "quiero una demo", "agendar demo", "ver demo", "mostrar demo", "probar demo"],
        follow_ups=["¿Cómo funciona en una tienda?", "Hablar por WhatsApp"],
    ),
    FAQ(
        key="soporte",
        title="¿Tengo soporte?",
        answer=(
            "Sí. La idea es que no te quedes solo con una herramienta, sino con una solución acompañada.\n\n"
            "Si necesitás ajustes, ayuda o querés revisar cómo está respondiendo, hay soporte para que el sistema siga funcionando bien y alineado con tu negocio."
        ),
        keywords=["soporte", "acompanamiento", "acompañamiento", "ayuda", "me ayudan", "asistencia"],
        follow_ups=["¿Qué pasa si quiero cambiar respuestas después?", "Hablar por WhatsApp"],
    ),
]

BASE_QUICK_REPLIES = ["¿Qué tipo de preguntas responde?"]

GREETING = "Hola 👋 ¿En qué puedo ayudarte?"

FALLBACK = (
    "No tengo una respuesta precisa para eso en este demo 😊\n\n"
    "Pero sí puedo ayudarte con temas como implementación, precios, funcionamiento, integración o cómo se adapta Nivora a una tienda."
)

ARGENTINA_LOCATIONS = [
    ("tucuman", "Tucumán"),
    ("cordoba", "Córdoba"),
    ("mendoza", "Mendoza"),
    ("santa fe", "Santa Fe"),
    ("buenos aires", "Buenos Aires"),
    ("salta", "Salta"),
    ("neuquen", "Neuquén"),
    ("misiones", "Misiones"),
    ("chaco", "Chaco"),
    ("corrientes", "Corrientes"),
    ("entre rios", "Entre Ríos"),
    ("jujuy", "Jujuy"),
    ("san juan", "San Juan"),
    ("san luis", "San Luis"),
    ("la pampa", "La Pampa"),
    ("rio negro", "Río Negro"),
    ("santiago del estero", "Santiago del Estero"),
    ("formosa", "Formosa"),
    ("catamarca", "Catamarca"),
    ("la rioja", "La Rioja"),
    ("chubut", "Chubut"),
    ("santa cruz", "Santa Cruz"),
    ("tierra del fuego", "Tierra del Fuego"),
    ("rosario", "Rosario"),
    ("mar del plata", "Mar del Plata"),
    ("la plata", "La Plata"),
    ("bahia blanca", "Bahía Blanca"),
]

INTERNATIONAL_COUNTRIES = [
    ("uruguay", "Uruguay"),
    ("brasil", "Brasil"),
    ("brazil", "Brasil"),
    ("chile", "Chile"),
    ("ecuador", "Ecuador"),
    ("espana", "España"),
    ("españa", "España"),
    ("mexico", "México"),
    ("méxico", "México"),
    ("colombia", "Colombia"),
    ("estados unidos", "Estados Unidos"),
    ("usa", "Estados Unidos"),
    ("eeuu", "Estados Unidos"),
    ("canada", "Canadá"),
    ("canadá", "Canadá"),
    ("alemania", "Alemania"),
    ("italia", "Italia"),
    ("francia", "Francia"),
    ("portugal", "Portugal"),
    ("paraguay", "Paraguay"),
    ("bolivia", "Bolivia"),
    ("peru", "Perú"),
    ("perú", "Perú"),
]

INTENT_PRIORITY = [
    "charla_basica",
    "saludo",
    "tipo_de_preguntas_que_responde",
    "implementacion_nivora",
    "consultas_internacionales",
    "envio_por_ubicacion",
    "precio",
    "funciona_realmente",
    "tipo_de_tienda",
    "personalizacion_bot",
    "uso",
    "cambios",
    "stock",
    "agradecimiento",
    "desconocido",
]

BUY_INTENT_KEYWORDS = {
    "me interesa",
    "quiero esto",
    "quiero sumarlo",
    "quiero para mi tienda",
    "quiero instalarlo",
    "quiero avanzar",
    "quiero contratar",
}

PRICING_INTENT_KEYWORDS = {
    "precio",
    "cual es el precio",
    "cuál es el precio",
    "cuanto cuesta",
    "cuánto cuesta",
    "cuanto sale",
    "cuánto sale",
    "cuanto vale",
    "cuánto vale",
    "planes",
    "plan",
    "costos",
    "costo",
    "mensual",
    "inversion",
    "inversión",
    "valor",
}

GUARANTEE_INTENT_KEYWORDS = {
    "tiene garantia",
    "tiene garantía",
    "y si no me sirve",
    "puedo cancelar",
    "riesgo",
    "sin riesgo",
    "garantia",
    "garantía",
    "devolucion",
    "devolución",
}

TIMING_INTENT_KEYWORDS = {
    "cuanto tarda",
    "cuánto tarda",
    "cuanto demora",
    "cuánto demora",
    "en cuanto tiempo",
    "en cuánto tiempo",
    "cuando estaria",
    "cuándo estaría",
    "cuando estaria listo",
    "cuándo estaría listo",
    "tiempo de implementacion",
    "tiempo de implementación",
    "tiempo de instalacion",
    "tiempo de instalación",
    "cuanto tiempo lleva",
    "cuánto tiempo lleva",
}

INSTALL_INTENT_KEYWORDS = {
    "instalacion",
    "instalación",
    "implementar",
    "implementacion",
    "implementación",
    "dificil de instalar",
    "difícil de instalar",
}

SHOPIFY_INTENT_KEYWORDS = {
    "shopify",
    "tienda nube",
    "tiendanube",
    "woocommerce",
    "plataforma",
}

CUSTOMIZATION_INTENT_KEYWORDS = {
    "adaptar",
    "personalizar",
    "mi negocio",
    "mi marca",
    "tono",
    "cambiar respuestas",
}

TECHNICAL_OBJECTION_KEYWORDS = {
    "no se programar",
    "no sé programar",
    "tecnico",
    "técnico",
    "codigo",
    "código",
}

DEMO_INTENT_KEYWORDS = {
    "demo",
    "verlo",
    "ver como funciona",
    "ver cómo funciona",
    "probar",
}

AI_INTENT_KEYWORDS = {
    "es como chatgpt",
    "es ia",
    "es inteligencia artificial",
    "funciona como una ia",
    "funciona como una inteligencia artificial",
    "chatgpt",
}

CONTACT_INTENT_KEYWORDS = {
    "contacto",
    "hablar con alguien",
    "whatsapp",
    "mail",
    "correo",
    "email",
}

FAQ_INDEX = {faq.key: faq for faq in FAQS}


def normalize_text(text: str) -> str:
    text = text.lower().strip()
    replacements = {
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "ñ": "n",
    }
    for a, b in replacements.items():
        text = text.replace(a, b)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def default_suggestions() -> List[str]:
    return BASE_QUICK_REPLIES.copy()


def single_follow_up(items: List[str] | None) -> List[str]:
    if not items:
        defaults = default_suggestions()
        return defaults[:1]
    return items[:1]


def contains_any(text: str, keywords: set[str]) -> bool:
    return any(normalize_text(keyword) in text for keyword in keywords)


def exact_match(text: str, keywords: set[str]) -> bool:
    return any(normalize_text(keyword) == text for keyword in keywords)


def count_matches(text: str, keywords: set[str] | list[str]) -> int:
    return sum(1 for keyword in keywords if normalize_text(keyword) in text)


def find_argentina_location(text: str) -> str | None:
    for normalized_name, display_name in ARGENTINA_LOCATIONS:
        if normalized_name in text:
            return display_name
    return None


def find_international_country(text: str) -> str | None:
    for normalized_name, display_name in INTERNATIONAL_COUNTRIES:
        if normalized_name in text:
            return display_name
    return None


def confidence_label(score: int) -> str:
    if score >= 2:
        return "alta"
    if score == 1:
        return "media"
    return "baja"


def build_location_shipping_reply(location: str) -> str:
    return (
        f"En {location} también podemos implementar Nivora 👍\n\n"
        "La activación suele quedar lista entre 24 y 72 horas, según la complejidad de tu tienda y la configuración inicial.\n\n"
        "Si querés, te contamos cuál sería la forma más simple de dejarlo funcionando en tu caso."
    )


def build_international_reply(country: str | None = None) -> str:
    place = country or "tu país"
    return (
        f"Sí, también podemos implementar Nivora en {place} 👍\n\n"
        f"Si estás fuera de Argentina, escribinos por mail a {SUPPORT_EMAIL} y te contamos cómo sería la implementación según tu caso y tu tienda.\n\n"
        "La idea es encontrar la mejor forma de adaptarlo para que también te funcione bien desde allá."
    )


def detect_intent(message: str) -> tuple[str, str, str | None]:
    text = normalize_text(message)
    location = find_argentina_location(text)
    country = find_international_country(text)

    charla_basica_keywords = {
        "como estas",
        "que tal",
        "todo bien",
        "como va",
    }
    saludo_keywords = {
        "hola",
        "holaa",
        "buenas",
        "buen dia",
        "buenos dias",
        "buenas tardes",
        "buenas noches",
        "hello",
        "hi",
    }
    implementacion_keywords = {
        "cuanto tarda",
        "cuanto demora",
        "en cuanto tiempo",
        "tarda mucho",
        "activacion",
        "activarse",
        "puesta en marcha",
        "instalarse",
        "integrarse",
        "configurarse",
        "implementarse",
        "dejarlo funcionando",
        "implementacion",
        "integracion",
        "configuracion",
        "instalar",
        "integrar",
        "configurar",
    }
    preguntas_keywords = {
        "que tipo de preguntas responde",
        "que puede responder",
        "que tipo de dudas responde",
        "que dudas responde",
        "que consultas responde",
        "preguntas frecuentes",
        "faq",
        "responde preguntas",
    }
    envio_general_keywords = {
        "cobertura",
        "zona",
        "localidad",
        "llega a",
        "a ",
    }
    precio_keywords = {
        "precio",
        "precios",
        "cuanto sale",
        "cuanto vale",
        "cuanto cuesta",
        "cuesta",
        "plan",
        "planes",
    }
    internacional_keywords = {
        "otros paises",
        "otros países",
        "fuera de argentina",
        "desde chile",
        "desde uruguay",
        "desde brasil",
        "desde ecuador",
        "funciona en",
        "sirve en",
        "puedo usarlo desde",
        "trabajan con",
        "se puede instalar si soy de",
        "lo pueden implementar en",
        "se puede usar en",
        "puede funcionar en",
    }
    funciona_realmente_keywords = {
        "funciona realmente",
        "esto funciona",
        "sirve de verdad",
        "vale la pena",
        "funciona bien",
        "funciona",
        "vale",
    }
    tipo_de_tienda_keywords = {
        "funciona para todo tipo de tiendas",
        "sirve para mi tienda",
        "se puede usar en cualquier negocio",
        "aplica a mi caso",
        "funciona para ecommerce",
        "funciona para tienda",
        "funciona para marca",
        "todo tipo de tiendas",
        "mi tienda",
        "cualquier negocio",
    }
    stock_keywords = {"stock", "disponible", "hay stock", "tenes stock"}
    uso_keywords = {
        "como se usa",
        "uso",
        "usar",
        "aplicar",
        "aplicacion",
        "sirve para mi caso",
        "sirve para mi",
    }
    cambios_keywords = {
        "cambio",
        "cambios",
        "devolucion",
        "devolver",
        "cambiar",
    }
    personalizacion_keywords = {
        "tono",
        "personalidad",
        "personalizar",
        "adaptar",
        "forma de responder",
        "estilo de respuesta",
        "como responde el bot",
        "como funciona el bot",
    }
    agradecimiento_keywords = {
        "gracias",
        "genial",
        "joya",
        "dale",
        "ok",
        "okay",
    }

    for intent in INTENT_PRIORITY:
        if intent == "charla_basica":
            score = count_matches(text, charla_basica_keywords)
            if score:
                return intent, confidence_label(score), None

        if intent == "saludo":
            score = 2 if exact_match(text, saludo_keywords) else 0
            if score:
                return intent, confidence_label(score), None

        if intent == "tipo_de_preguntas_que_responde":
            score = count_matches(text, preguntas_keywords)
            if score:
                return intent, confidence_label(score), None

        if intent == "implementacion_nivora":
            if country:
                score = count_matches(text, implementacion_keywords | internacional_keywords)
                if score:
                    return "consultas_internacionales", confidence_label(score), country
            score = count_matches(text, implementacion_keywords)
            if score:
                return intent, confidence_label(score), None

        if intent == "consultas_internacionales":
            score = count_matches(text, internacional_keywords)
            if country:
                score += 1
                if text == normalize_text(country):
                    score += 1
                if any(
                    phrase in text
                    for phrase in {
                        f"funciona en {normalize_text(country)}",
                        f"sirve en {normalize_text(country)}",
                        f"desde {normalize_text(country)}",
                        f"instalar si soy de {normalize_text(country)}",
                        f"implementar en {normalize_text(country)}",
                    }
                ):
                    score += 1
            if score:
                return intent, confidence_label(score), country

        if intent == "envio_por_ubicacion" and location:
            score = count_matches(text, envio_general_keywords)
            if text == normalize_text(location):
                score += 1
            if text == f"a {normalize_text(location)}":
                score += 1
            if any(
                phrase in text
                for phrase in {
                    f"y a {normalize_text(location)}",
                    f"cobertura en {normalize_text(location)}",
                    f"llega a {normalize_text(location)}",
                    f"en {normalize_text(location)}",
                }
            ):
                score += 1
            if score:
                return intent, confidence_label(score), location

        if intent == "precio":
            score = count_matches(text, precio_keywords)
            if score:
                return intent, confidence_label(score), None

        if intent == "funciona_realmente":
            score = count_matches(text, funciona_realmente_keywords)
            if score:
                return intent, confidence_label(score), None

        if intent == "tipo_de_tienda":
            score = count_matches(text, tipo_de_tienda_keywords)
            if score:
                return intent, confidence_label(score), None

        if intent == "stock":
            score = count_matches(text, stock_keywords)
            if score:
                return intent, confidence_label(score), None

        if intent == "uso":
            score = count_matches(text, uso_keywords)
            if score:
                return intent, confidence_label(score), None

        if intent == "cambios":
            score = count_matches(text, cambios_keywords)
            if score:
                return intent, confidence_label(score), None

        if intent == "personalizacion_bot":
            score = count_matches(text, personalizacion_keywords)
            if score:
                return intent, confidence_label(score), None

        if intent == "agradecimiento":
            score = 2 if exact_match(text, agradecimiento_keywords) else 0
            if score:
                return intent, confidence_label(score), None

    return "desconocido", "baja", None


def get_faq(key: str) -> FAQ | None:
    return FAQ_INDEX.get(key)


def find_best_faq(message: str) -> FAQ | None:
    text = normalize_text(message)
    best_faq = None
    best_score = 0

    for faq in FAQS:
        score = 0
        for keyword in faq.keywords:
            keyword_norm = normalize_text(keyword)
            if keyword_norm in text:
                score += 3
        title_words = normalize_text(faq.title).split()
        score += sum(1 for w in title_words if len(w) > 3 and w in text)
        if score > best_score:
            best_score = score
            best_faq = faq

    return best_faq if best_score > 0 else None


def generate_response(intent: str, location: str | None = None) -> tuple[str, List[str]]:
    if intent == "charla_basica":
        return "¡Muy bien! 😊\n\nGracias por preguntar. ¿En qué te puedo ayudar hoy?", default_suggestions()

    if intent == "saludo":
        return "¡Hola! 👋\n\nAcá estoy para ayudarte. ¿Qué querés consultar?", default_suggestions()

    if intent == "tipo_de_preguntas_que_responde":
        faq = get_faq("preguntas")
        if faq:
            return faq.answer, single_follow_up(faq.follow_ups)

    if intent == "implementacion_nivora":
        return (
            "La implementación suele tardar entre 24 y 72 horas 👍\n\n"
            "Depende del plan elegido y de la complejidad de tu tienda, pero la idea es dejarlo funcionando lo antes posible para que puedas empezar a usarlo sin demoras.\n\n"
            "Si querés, también podés ver qué plan se adapta mejor a tu tienda en la pestaña Precios."
        ), ["Precios"]

    if intent == "envio_por_ubicacion" and location:
        return build_location_shipping_reply(location), ["Precios"]

    if intent == "precio":
        return (
            "Podés ver todos los precios en la pestaña 'Precios' 👍\n\n"
            "Ahí vas a encontrar los planes disponibles para elegir el que mejor se adapte a tu tienda y a lo que necesitás hoy.\n\n"
            "Si querés, te contamos cuál encaja mejor según tu caso."
        ), ["Precios"]

    if intent == "consultas_internacionales":
        return build_international_reply(location), []

    if intent == "funciona_realmente":
        return (
            "Sí, funciona 👍\n\n"
            "La idea es responder en el momento justo, cuando el cliente está por decidir, y eso ayuda mucho a aumentar conversiones.\n\n"
            "Muchos negocios pierden ventas solo por no responder a tiempo, y esto viene justamente a resolver eso."
        ), ["¿Qué beneficios tiene?"]

    if intent == "tipo_de_tienda":
        return (
            "Sí, se puede adaptar a todo tipo de tiendas 👍\n\n"
            "Se integra según tu negocio y se ajusta a lo que vendés, para responder dudas reales de tus clientes.\n\n"
            "La idea es que encaje con tu tienda y acompañe la compra de forma natural."
        ), ["¿Cómo funciona en una tienda?"]

    if intent == "stock":
        faq = get_faq("stock_simple")
        if faq:
            return faq.answer, single_follow_up(faq.follow_ups)

    if intent == "uso":
        faq = get_faq("uso_simple")
        if faq:
            return faq.answer, single_follow_up(faq.follow_ups)

    if intent == "cambios":
        faq = get_faq("cambios_simple")
        if faq:
            return faq.answer, single_follow_up(faq.follow_ups)

    if intent == "personalizacion_bot":
        faq = get_faq("personalizacion_tono")
        if faq:
            return faq.answer, single_follow_up(faq.follow_ups)

    if intent == "agradecimiento":
        return "¡De nada! 😊\n\nSi querés, podés preguntarme otra cosa.", default_suggestions()

    return FALLBACK, single_follow_up(default_suggestions())


def build_reply(message: str) -> tuple[str, List[str]]:
    intent, confidence, location = detect_intent(message)
    print("INTENT:", intent, "CONFIDENCE:", confidence, "LOCATION:", location)

    if confidence == "baja":
        return generate_response("desconocido")

    return generate_response(intent, location)


@app.get("/")
def home():
    return render_template_string(HOME_HTML, brand_name=BRAND_NAME)


@app.get("/health")
def health():
    return jsonify({"ok": True, "service": BRAND_NAME})


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response


@app.get("/config")
def config():
    return jsonify(
        {
            "brand_name": BRAND_NAME,
            "primary_color": PRIMARY_COLOR,
            "secondary_color": SECONDARY_COLOR,
            "quick_replies": default_suggestions(),
            "support_email": SUPPORT_EMAIL,
            "greeting": GREETING,
        }
    )


@app.route("/chat", methods=["POST", "OPTIONS"])
def chat():
    if request.method == "OPTIONS":
        return Response(status=204)

    data = request.get_json(silent=True) or {}
    message = str(data.get("message", "")).strip()

    print("USER:", message)
    
    if not message:
        return jsonify({"reply": "Escribime tu consulta y te ayudo.", "suggestions": default_suggestions()}), 400

    reply, suggestions = build_reply(message)
    return jsonify({"reply": reply, "suggestions": suggestions})


@app.get("/widget")
def widget():
    return render_template_string(
        WIDGET_HTML,
        brand_name=BRAND_NAME,
        primary_color=PRIMARY_COLOR,
        secondary_color=SECONDARY_COLOR,
        support_email=SUPPORT_EMAIL,
    )


@app.get("/widget.js")
def widget_js():
    base_url = request.host_url.rstrip("/")
    script = WIDGET_JS.replace("__BASE_URL__", base_url)
    return Response(script, mimetype="application/javascript")


HOME_HTML = """
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ brand_name }} Demo</title>
  <style>
    :root{
      --bg:#07090f;
      --bg-2:#0d1320;
      --panel:rgba(13,18,30,.88);
      --line:rgba(255,255,255,.08);
      --text:#f7f8fc;
      --muted:#98a2b3;
      --accent:#d6c29a;
      --user:#131a29;
      --bot:rgba(255,255,255,.05);
      --shadow:0 30px 80px rgba(0,0,0,.42);
    }
    *{box-sizing:border-box}
    body{
      margin:0;
      min-height:100vh;
      display:grid;
      place-items:center;
      padding:32px 16px;
      font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
      background:
        radial-gradient(circle at 15% 20%, rgba(214,194,154,.11), transparent 24%),
        radial-gradient(circle at 82% 14%, rgba(99,102,241,.12), transparent 22%),
        linear-gradient(180deg, #05070c 0%, #0a0d15 50%, #06080f 100%);
      color:var(--text);
    }
    .demo-shell{
      width:min(100%, 960px);
      display:grid;
      gap:18px;
      justify-items:center;
    }
    .demo-kicker{
      color:#e7d8b8;
      font-size:13px;
      font-weight:600;
      letter-spacing:.14em;
      text-transform:uppercase;
    }
    .demo-chat{
      width:min(100%, 720px);
      min-height:680px;
      display:flex;
      flex-direction:column;
      border:1px solid var(--line);
      border-radius:30px;
      overflow:hidden;
      background:
        radial-gradient(circle at top, rgba(214,194,154,.08), transparent 28%),
        linear-gradient(180deg, rgba(16,21,34,.96), rgba(9,12,20,.98));
      box-shadow:var(--shadow);
    }
    .demo-header{
      padding:22px 24px 18px;
      border-bottom:1px solid rgba(255,255,255,.06);
      background:linear-gradient(180deg, rgba(255,255,255,.03), rgba(255,255,255,.01));
    }
    .demo-title{
      margin:0;
      font-size:15px;
      font-weight:700;
      letter-spacing:-.02em;
    }
    .demo-status{
      display:inline-flex;
      align-items:center;
      gap:8px;
      margin-top:7px;
      color:var(--muted);
      font-size:12.5px;
    }
    .demo-status::before{
      content:"";
      width:8px;
      height:8px;
      border-radius:999px;
      background:#53d38b;
      box-shadow:0 0 12px rgba(83,211,139,.4);
    }
    .demo-messages{
      flex:1;
      display:flex;
      flex-direction:column;
      gap:10px;
      padding:22px 18px 18px;
      overflow:auto;
    }
    .msg{
      max-width:82%;
      padding:14px 16px;
      border-radius:20px;
      line-height:1.6;
      font-size:14px;
      animation:fadeUp .28s ease;
    }
    .msg.bot{
      align-self:flex-start;
      background:var(--bot);
      border:1px solid rgba(255,255,255,.07);
      color:var(--text);
      border-top-left-radius:10px;
    }
    .msg.user{
      align-self:flex-end;
      background:linear-gradient(135deg, #151d2d, #1b2436);
      border:1px solid rgba(255,255,255,.06);
      color:#fff;
      border-top-right-radius:10px;
    }
    .quick-replies{
      display:flex;
      flex-wrap:wrap;
      gap:10px;
      padding:0 18px 18px;
    }
    .quick-replies button{
      border:1px solid rgba(255,255,255,.08);
      background:rgba(255,255,255,.04);
      color:#f4f6fb;
      border-radius:999px;
      padding:10px 14px;
      font-size:12.5px;
      font-weight:600;
      cursor:pointer;
      transition:transform .2s ease, border-color .2s ease, background .2s ease;
    }
    .quick-replies button:hover{
      transform:translateY(-1px);
      border-color:rgba(214,194,154,.22);
      background:rgba(255,255,255,.06);
    }
    .demo-input{
      display:flex;
      gap:10px;
      padding:16px 18px 18px;
      border-top:1px solid rgba(255,255,255,.06);
      background:rgba(255,255,255,.02);
    }
    .demo-input input{
      flex:1;
      border:1px solid rgba(255,255,255,.08);
      border-radius:999px;
      padding:13px 15px;
      background:rgba(255,255,255,.03);
      color:var(--text);
      outline:none;
    }
    .demo-input input::placeholder{
      color:var(--muted);
    }
    .demo-input button{
      border:1px solid rgba(214,194,154,.24);
      border-radius:999px;
      padding:13px 16px;
      background:linear-gradient(135deg, rgba(214,194,154,.95), rgba(241,232,205,.98));
      color:#0b0d13;
      font-weight:700;
      cursor:pointer;
    }
    @keyframes fadeUp{
      from{opacity:0;transform:translateY(8px)}
      to{opacity:1;transform:translateY(0)}
    }
    @media (max-width: 760px){
      body{padding:16px 10px}
      .demo-chat{
        min-height:72vh;
        border-radius:24px;
      }
      .msg{
        max-width:90%;
      }
      .quick-replies{
        flex-direction:column;
      }
      .quick-replies button,
      .demo-input button{
        width:100%;
      }
      .demo-input{
        flex-direction:column;
      }
    }
  </style>
</head>
<body>
  <div class="demo-shell">
    <div class="demo-kicker">Así responde en tu tienda</div>

    <div class="demo-chat">
      <div class="demo-header">
        <p class="demo-title">Asistente</p>
        <div class="demo-status">En línea</div>
      </div>

      <div id="messages" class="demo-messages">
        <div class="msg bot">Hola 👋 ¿En qué puedo ayudarte?</div>
      </div>

      <div id="quickReplies" class="quick-replies">
        <button type="button" data-question="¿Qué tipo de preguntas responde?">¿Qué tipo de preguntas responde?</button>
        <button type="button" data-question="¿Cuánto tarda el envío?">¿Cuánto tarda el envío?</button>
        <button type="button" data-question="¿Sirve para mi caso?">¿Sirve para mi caso?</button>
      </div>

      <div class="demo-input">
        <input id="demoInput" type="text" placeholder="Escribí tu consulta..." />
        <button id="demoSend" type="button">Enviar</button>
      </div>
    </div>
  </div>

  <script>
    const messagesEl = document.getElementById("messages");
    const quickRepliesEl = document.getElementById("quickReplies");
    const inputEl = document.getElementById("demoInput");
    const sendBtn = document.getElementById("demoSend");

    function addMessage(text, who) {
      const el = document.createElement("div");
      el.className = "msg " + who;
      el.textContent = text;
      messagesEl.appendChild(el);
      messagesEl.scrollTo({ top: messagesEl.scrollHeight, behavior: "smooth" });
    }

    function renderQuickReplies(items) {
      quickRepliesEl.innerHTML = "";
      (items || []).forEach((item) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.textContent = item;
        btn.addEventListener("click", () => sendMessage(item));
        quickRepliesEl.appendChild(btn);
      });
    }

    async function loadConfig() {
      const res = await fetch("/config");
      const config = await res.json();
      messagesEl.innerHTML = "";
      addMessage(config.greeting || "Hola 👋 ¿En qué puedo ayudarte?", "bot");
      renderQuickReplies(config.quick_replies || []);
    }

    async function sendMessage(message) {
      const text = (message ?? inputEl.value).trim();
      if (!text) return;

      addMessage(text, "user");
      inputEl.value = "";
      renderQuickReplies([]);

      try {
        const res = await fetch("/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: text })
        });
        const data = await res.json();
        window.setTimeout(() => {
          addMessage(data.reply || "No tengo una respuesta precisa para eso en este demo 😊", "bot");
          renderQuickReplies((data.suggestions || []).slice(0, 1));
        }, 260);
      } catch (error) {
        window.setTimeout(() => {
          addMessage("No pude responder en este momento. Intentá de nuevo en unos segundos.", "bot");
          renderQuickReplies(["¿Qué tipo de preguntas responde?"]);
        }, 260);
      }
    }

    sendBtn.addEventListener("click", () => sendMessage());
    inputEl.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
      }
    });

    loadConfig();
  </script>
</body>
</html>
"""


WIDGET_HTML = """
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ brand_name }} Chat</title>
  <style>
    :root {
      --primary: {{ primary_color }};
      --secondary: {{ secondary_color }};
      --bg: #f5f7fb;
      --surface: rgba(255, 255, 255, 0.96);
      --surface-soft: rgba(248, 250, 252, 0.92);
      --text: #0f172a;
      --muted: #667085;
      --border: rgba(15, 23, 42, 0.08);
      --border-strong: rgba(15, 23, 42, 0.12);
      --bubble-bot: #ffffff;
      --bubble-user: #111827;
      --shadow: 0 24px 80px rgba(15, 23, 42, 0.14);
      --shadow-soft: 0 10px 30px rgba(15, 23, 42, 0.08);
    }
    *{box-sizing:border-box}
    html,body{height:100%}
    body{
      margin:0;
      font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
      background:linear-gradient(180deg, #f7f9fc 0%, #eef3f8 100%);
      color:var(--text)
    }
    .chat{
      display:flex;
      flex-direction:column;
      height:100vh;
      background:
        radial-gradient(circle at top right, rgba(6,182,212,.08), transparent 22%),
        linear-gradient(180deg, rgba(255,255,255,.98), rgba(247,249,252,.98));
    }
    .header{
      position: relative;
      padding:18px 18px 16px;
      background:
        linear-gradient(135deg, rgba(15,23,42,.96), rgba(17,24,39,.92)),
        linear-gradient(135deg,var(--primary),var(--secondary));
      color:#fff;
      border-bottom:1px solid rgba(255,255,255,.08);
    }
    .header::after{
      content:"";
      position:absolute;
      inset:auto 18px 0 18px;
      height:1px;
      background:linear-gradient(90deg, transparent, rgba(255,255,255,.22), transparent);
    }
    .close-btn{
      position:absolute;
      top:14px;
      right:14px;
      width:34px;
      height:34px;
      display:inline-flex;
      align-items:center;
      justify-content:center;
      background:rgba(255,255,255,.08);
      border:1px solid rgba(255,255,255,.1);
      border-radius:999px;
      color:#fff;
      font-size:16px;
      line-height:1;
      cursor:pointer;
      transition:background .2s ease, transform .2s ease, border-color .2s ease;
    }
    .close-btn:hover{
      background:rgba(255,255,255,.14);
      border-color:rgba(255,255,255,.18);
      transform:translateY(-1px);
    }
    .header-title{
      font-size:15px;
      font-weight:700;
      letter-spacing:-0.02em;
    }
    .header-sub{
      max-width:260px;
      font-size:12.5px;
      line-height:1.45;
      opacity:.78;
      margin-top:6px
    }
    .messages{
      flex:1;
      overflow:auto;
      padding:16px 16px;
      background:transparent;
      scroll-behavior:smooth;
    }
    .messages::-webkit-scrollbar{width:10px}
    .messages::-webkit-scrollbar-thumb{
      background:rgba(15,23,42,.12);
      border:3px solid transparent;
      border-radius:999px;
      background-clip:padding-box;
    }
    .msg{
      max-width:87%;
      padding:13px 15px;
      border-radius:18px;
      margin:8px 0;
      line-height:1.58;
      white-space:pre-wrap;
      font-size:14px;
      box-shadow:var(--shadow-soft);
      overflow:visible;
    }
    .bot{
      background:var(--bubble-bot);
      border:1px solid var(--border);
      border-top-left-radius:8px;
      color:var(--text);
    }
    .user{
      background:linear-gradient(135deg, #111827, #1f2937);
      color:#fff;
      margin-left:auto;
      border-top-right-radius:8px;
      box-shadow:0 12px 28px rgba(17,24,39,.18);
    }
    .quick{
      padding:10px 12px 8px;
      background:rgba(255,255,255,.82);
      backdrop-filter:blur(12px);
      border-top:1px solid var(--border);
      display:flex;
      gap:8px;
      flex-wrap:wrap
    }
    .quick button{
      border:1px solid rgba(15,23,42,.08);
      border-radius:999px;
      padding:8px 11px;
      background:rgba(255,255,255,.92);
      color:#0f172a;
      cursor:pointer;
      font-size:12px;
      font-weight:600;
      letter-spacing:-0.01em;
      box-shadow:0 6px 18px rgba(15,23,42,.05);
      transition:transform .2s ease, box-shadow .2s ease, border-color .2s ease, background .2s ease;
    }
    .quick button:hover{
      transform:translateY(-1px);
      border-color:rgba(15,23,42,.14);
      box-shadow:0 10px 24px rgba(15,23,42,.08);
      background:#fff;
    }
    .composer{
      display:flex;
      gap:8px;
      padding:11px 12px;
      background:rgba(255,255,255,.9);
      backdrop-filter:blur(14px);
      border-top:1px solid var(--border)
    }
    .composer input{
      flex:1;
      border:1px solid var(--border);
      border-radius:999px;
      padding:11px 14px;
      font-size:14px;
      background:rgba(248,250,252,.92);
      color:var(--text);
      outline:none;
      transition:border-color .2s ease, box-shadow .2s ease, background .2s ease;
    }
    .composer input:focus{
      border-color:rgba(6,182,212,.35);
      box-shadow:0 0 0 4px rgba(6,182,212,.08);
      background:#fff;
    }
    .composer button{
      border:none;
      border-radius:999px;
      padding:11px 16px;
      background:linear-gradient(135deg, var(--primary), var(--secondary));
      color:#fff;
      font-weight:700;
      cursor:pointer;
      letter-spacing:-0.01em;
      box-shadow:0 12px 28px rgba(15,23,42,.18);
      transition:transform .2s ease, box-shadow .2s ease, filter .2s ease;
    }
    .composer button:hover{
      transform:translateY(-1px);
      filter:brightness(1.02);
      box-shadow:0 16px 34px rgba(15,23,42,.22);
    }
    .footer{
      padding:8px 12px 10px;
      font-size:11px;
      line-height:1.5;
      color:var(--muted);
      background:rgba(255,255,255,.88);
      border-top:1px solid var(--border)
    }
    a{color:inherit}
    @media (max-width: 600px){
      .header{padding:18px 16px 15px}
      .header-sub{max-width:100%;padding-right:36px}
      .messages{padding:14px 12px}
      .msg{max-width:90%;font-size:13.5px}
      .quick{padding:9px 10px 8px}
      .quick button{font-size:11.5px;padding:7px 10px}
      .composer{padding:10px}
      .composer input{font-size:16px}
      .close-btn{top:12px;right:12px}
    }
  </style>
</head>
<body>
  <div class="chat">
    <div class="header">
        <button id="closeBtn" class="close-btn">✕</button>
        <div class="header-title">{{ brand_name }}</div>
        <div class="header-sub">Asistente de ventas y atención para ecommerce</div>
    </div>

    <div id="messages" class="messages"></div>

    <div class="quick" id="quickReplies"></div>

    <div class="composer">
      <input id="messageInput" type="text" placeholder="Escribí tu consulta..." />
      <button id="sendBtn">Enviar</button>
    </div>

    <div class="footer">
      Atención personalizada: <a href="mailto:{{ support_email }}">{{ support_email }}</a>
    </div>
  </div>

<script>
  const messagesEl = document.getElementById('messages');
  const quickRepliesEl = document.getElementById('quickReplies');
  const inputEl = document.getElementById('messageInput');
  const sendBtn = document.getElementById('sendBtn');

  function addMessage(text, who) {
    const el = document.createElement('div');
    el.className = 'msg ' + who;
    el.textContent = text;
    messagesEl.appendChild(el);
    requestAnimationFrame(() => {
      if (who === 'bot') {
        const targetTop = Math.max(0, el.offsetTop - 8);
        messagesEl.scrollTo({ top: targetTop, behavior: 'smooth' });
      } else {
        messagesEl.scrollTo({ top: messagesEl.scrollHeight, behavior: 'smooth' });
      }
    });
  }

  function renderQuickReplies(items) {
    quickRepliesEl.innerHTML = '';
    (items || []).forEach((item) => {
      const btn = document.createElement('button');
      btn.textContent = item;
      btn.onclick = () => sendMessage(item);
      quickRepliesEl.appendChild(btn);
    });
  }

  async function loadConfig() {
    const res = await fetch('/config');
    const config = await res.json();
    renderQuickReplies(config.quick_replies || []);
    addMessage(config.greeting || `Hola, soy el asistente de ${config.brand_name}. ¿En qué puedo ayudarte?`, 'bot');
  }

  async function sendMessage(message) {
    const text = (message ?? inputEl.value).trim();
    if (!text) return;
    addMessage(text, 'user');
    inputEl.value = '';

    try {
      const res = await fetch('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text })
      });
      const data = await res.json();
      addMessage(data.reply || 'Hubo un error al responder.', 'bot');
      renderQuickReplies(data.suggestions || []);
    } catch (err) {
      addMessage('Hubo un problema al responder. Intentá de nuevo en unos segundos.', 'bot');
    }
  }

  sendBtn.addEventListener('click', () => sendMessage());
  inputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') sendMessage();
  });

  loadConfig();
document.getElementById('closeBtn').addEventListener('click', function () {
  window.parent.postMessage('closeChat', '*');
});
</script>
</body>
</html>
"""


WIDGET_JS = r"""
(function () {
  if (window.__ACQUALUME_BOT_LOADED__) return;
  window.__ACQUALUME_BOT_LOADED__ = true;

  var baseUrl = "__BASE_URL__";

  var style = document.createElement('style');
  style.textContent = [
    '@keyframes nivoraPulse {',
    '  0%, 100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.45); }',
    '  50% { transform: scale(1.06); box-shadow: 0 0 0 8px rgba(239, 68, 68, 0); }',
    '}',
    '@keyframes nivoraTyping {',
    '  0%, 80%, 100% { opacity: 0.3; transform: translateY(0); }',
    '  40% { opacity: 1; transform: translateY(-2px); }',
    '}'
  ].join('');
  document.head.appendChild(style);

  var launcher = document.createElement('div');
  launcher.style.position = 'fixed';
  launcher.style.right = '20px';
  launcher.style.bottom = '20px';
  launcher.style.display = 'flex';
  launcher.style.alignItems = 'flex-end';
  launcher.style.gap = '10px';
  launcher.style.flexDirection = 'row-reverse';
  launcher.style.zIndex = '999999';
  launcher.style.opacity = '0';
  launcher.style.transform = 'translateY(14px)';
  launcher.style.transition = 'opacity .45s ease, transform .45s ease';

  var teaser = document.createElement('button');
  teaser.type = 'button';
  teaser.setAttribute('aria-label', 'Abrir chat');
  teaser.style.display = 'flex';
  teaser.style.flexDirection = 'column';
  teaser.style.alignItems = 'flex-start';
  teaser.style.gap = '8px';
  teaser.style.maxWidth = '220px';
  teaser.style.padding = '14px 16px';
  teaser.style.border = '1px solid rgba(255,255,255,0.08)';
  teaser.style.borderRadius = '22px 22px 22px 8px';
  teaser.style.background = 'linear-gradient(180deg, rgba(18,24,38,0.96), rgba(12,16,27,0.96))';
  teaser.style.color = '#f8fafc';
  teaser.style.boxShadow = '0 18px 42px rgba(15,23,42,0.22)';
  teaser.style.cursor = 'pointer';
  teaser.style.textAlign = 'left';
  teaser.style.backdropFilter = 'blur(14px)';
  teaser.style.transition = 'transform .22s ease, box-shadow .22s ease, border-color .22s ease';
  teaser.style.borderRadius = '22px 22px 8px 22px';

  var typing = document.createElement('div');
  typing.style.display = 'flex';
  typing.style.gap = '4px';

  ['0s', '.15s', '.3s'].forEach(function (delay) {
    var dot = document.createElement('span');
    dot.style.width = '6px';
    dot.style.height = '6px';
    dot.style.borderRadius = '999px';
    dot.style.background = 'rgba(214,194,154,0.88)';
    dot.style.animation = 'nivoraTyping 1.4s infinite';
    dot.style.animationDelay = delay;
    typing.appendChild(dot);
  });

  var teaserText = document.createElement('div');
  teaserText.textContent = 'Estoy para ayudarte 👍';
  teaserText.style.fontSize = '14px';
  teaserText.style.fontWeight = '600';
  teaserText.style.lineHeight = '1.45';
  teaserText.style.letterSpacing = '-0.01em';

  teaser.appendChild(typing);
  teaser.appendChild(teaserText);

  var avatar = document.createElement('button');
  avatar.type = 'button';
  avatar.setAttribute('aria-label', 'Abrir chat');
  avatar.style.position = 'relative';
  avatar.style.width = '62px';
  avatar.style.height = '62px';
  avatar.style.border = '1px solid rgba(255,255,255,0.14)';
  avatar.style.borderRadius = '999px';
  avatar.style.background = 'linear-gradient(135deg, #111827, #1f2937 58%, #5b63ff 140%)';
  avatar.style.color = '#fff';
  avatar.style.fontSize = '20px';
  avatar.style.fontWeight = '700';
  avatar.style.letterSpacing = '-0.03em';
  avatar.style.cursor = 'pointer';
  avatar.style.boxShadow = '0 18px 40px rgba(15,23,42,.2)';
  avatar.style.transition = 'transform .22s ease, box-shadow .22s ease, filter .22s ease';
  avatar.innerHTML = [
    '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">',
    '<path d="M7 8.75C7 7.50736 8.00736 6.5 9.25 6.5H14.75C15.9926 6.5 17 7.50736 17 8.75V12.25C17 13.4926 15.9926 14.5 14.75 14.5H11.9L9.2 17V14.5H9.25C8.00736 14.5 7 13.4926 7 12.25V8.75Z" stroke="white" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>',
    '</svg>'
  ].join('');

  var badge = document.createElement('span');
  badge.textContent = '1';
  badge.style.position = 'absolute';
  badge.style.top = '-1px';
  badge.style.right = '-1px';
  badge.style.width = '22px';
  badge.style.height = '22px';
  badge.style.display = 'inline-flex';
  badge.style.alignItems = 'center';
  badge.style.justifyContent = 'center';
  badge.style.borderRadius = '999px';
  badge.style.background = '#ef4444';
  badge.style.color = '#fff';
  badge.style.fontSize = '11px';
  badge.style.fontWeight = '700';
  badge.style.border = '2px solid rgba(11, 13, 19, 0.92)';
  badge.style.animation = 'nivoraPulse 2.8s ease-in-out infinite';
  avatar.appendChild(badge);

  var frame = document.createElement('iframe');
  frame.src = baseUrl + '/widget';
  frame.style.position = 'fixed';
  frame.style.right = '20px';
  frame.style.bottom = '92px';
  frame.style.width = '392px';
  frame.style.maxWidth = 'calc(100vw - 24px)';
  frame.style.height = '640px';
  frame.style.maxHeight = 'calc(100vh - 120px)';
  frame.style.border = 'none';
  frame.style.borderRadius = '24px';
  frame.style.boxShadow = '0 28px 80px rgba(15, 23, 42, .22)';
  frame.style.overflow = 'hidden';
  frame.style.background = '#fff';
  frame.style.zIndex = '999998';
  frame.style.display = 'none';

  if (window.innerWidth <= 600) {
    launcher.style.left = 'auto';
    launcher.style.right = '12px';
    launcher.style.bottom = '16px';
    launcher.style.gap = '8px';
    launcher.style.flexDirection = 'row-reverse';
    teaser.style.maxWidth = 'min(68vw, 210px)';
    teaser.style.padding = '12px 14px';
    teaserText.style.fontSize = '13px';
    avatar.style.width = '58px';
    avatar.style.height = '58px';
    frame.style.right = '12px';
    frame.style.bottom = '84px';
    frame.style.width = 'calc(100vw - 24px)';
    frame.style.height = 'min(680px, calc(100vh - 104px))';
    frame.style.borderRadius = '22px';
  }

  function setHoverState(active) {
    teaser.style.transform = active ? 'translateY(-2px)' : 'translateY(0)';
    teaser.style.boxShadow = active ? '0 24px 56px rgba(15,23,42,0.28)' : '0 18px 42px rgba(15,23,42,0.22)';
    teaser.style.borderColor = active ? 'rgba(214,194,154,0.16)' : 'rgba(255,255,255,0.08)';
    avatar.style.transform = active ? 'translateY(-2px)' : 'translateY(0)';
    avatar.style.filter = active ? 'brightness(1.03)' : 'brightness(1)';
    avatar.style.boxShadow = active ? '0 24px 52px rgba(15,23,42,.26)' : '0 18px 40px rgba(15,23,42,.2)';
  }

  function toggleChat() {
    var isOpen = frame.style.display === 'block';
    frame.style.display = isOpen ? 'none' : 'block';
    launcher.style.display = isOpen ? 'flex' : 'none';
  }

  teaser.addEventListener('mouseenter', function () { setHoverState(true); });
  avatar.addEventListener('mouseenter', function () { setHoverState(true); });
  teaser.addEventListener('mouseleave', function () { setHoverState(false); });
  avatar.addEventListener('mouseleave', function () { setHoverState(false); });
  teaser.addEventListener('click', toggleChat);
  avatar.addEventListener('click', toggleChat);

  launcher.appendChild(teaser);
  launcher.appendChild(avatar);

  document.body.appendChild(frame);
  document.body.appendChild(launcher);

  window.setTimeout(function () {
    launcher.style.opacity = '1';
    launcher.style.transform = 'translateY(0)';
  }, 1500);

  window.addEventListener('message', function (event) {
    if (event.data === 'closeChat') {
      frame.style.display = 'none';
      launcher.style.display = 'flex';
    }
  });
})();
"""


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=True)
