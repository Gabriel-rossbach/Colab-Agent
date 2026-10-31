"""Planejador: transforma um pedido em tarefas e diz em qual máquina cada uma roda.

Formato da resposta do modelo, uma linha por tarefa: [cpuN] [tarefaK] prompt
- A numeração K recomeça em 1 em cada máquina.
- Cada máquina recebe no máximo 2 tarefas (tarefa1 e tarefa2).
- As máquinas são usadas em ordem, sem pular: cpu1, depois cpu2, e assim por diante.

Não depende de Colab nem de GPU. Teste com: python plano.py
"""
import base64
import difflib
import re

MODELO_PLANEJADOR = "gpt-oss:20b"
MIN_CARACTERES = 40
MAX_MAQUINAS = 5                              # cpu1 a cpu5
MAX_POR_MAQUINA = 2                           # tarefa1 e tarefa2 dentro de cada máquina
MAX_TAREFAS = MAX_MAQUINAS * MAX_POR_MAQUINA  # 10
LIMIAR_QUASE_IGUAL = 0.985                    # acima disso, duas tarefas são tratadas como cópias
PALAVRAS_EXTRAS = ("segurança", "seguranca", "seguro", "cuidado")  # boilerplate que o pedido não trouxe

SKILL_PLANEJADOR = """\
Você é o planejador de um sistema com __MAQ__ máquinas de pesquisa (cpu1 a cpu__MAQ__). Cada máquina roda um agente que só conhece o próprio prompt e tem a ferramenta web_search. Você decide o que cada máquina pesquisa.

Regras do que pesquisar:
- Uma tarefa para cada categoria pedida. A tarefa pesquisa a categoria inteira, com a quantidade pedida: "5 carros" fica numa tarefa só.
- Só o que o pedido pediu. Não crie ângulos ou subtemas que o pedido não trouxe, como segurança, navegação, café ou bateria. Não crie tarefas fora do tema.
- Se o pedido trouxer nomes, use exatamente esses nomes.
- Se o pedido NÃO trouxer nomes, não invente nomes de plugins, skills, produtos ou sites, nem entre aspas. Descreva a categoria e mande o agente achar os nomes com web_search.
- Não crie tarefas sobre contornar bloqueios, Cloudflare, anti-bot ou captcha.
- No máximo __MAX__ tarefas.

Distribuição entre máquinas (obrigatória):
- Cada máquina recebe no máximo __POR__ tarefas: tarefa1 e tarefa2. A numeração recomeça em 1 em cada máquina.
- 1 tarefa: cpu1 tarefa1.
- Pedido simples (2 a 4 tarefas): use 2 máquinas e divida as tarefas entre elas. Com 2 tarefas: cpu1 tarefa1 e cpu2 tarefa1. Com 3 tarefas: cpu1 tarefa1 e tarefa2, e cpu2 tarefa1.
- Pedido com 5 ou mais tarefas: use o mínimo de máquinas, com 2 tarefas em cada uma. Com 5 tarefas: cpu1 (tarefa1 e tarefa2), cpu2 (tarefa1 e tarefa2) e cpu3 (tarefa1).
- Nunca use cpu6 ou um número maior.
- Cada máquina ligada custa caro. Por isso, nunca use mais máquinas do que a regra acima pede.

Conteúdo de cada prompt:
- Comece com "Use web_search para pesquisar" e peça exatamente o que o pedido pediu, em português, numa linha só.
- Não acrescente cuidados de segurança, fontes, ângulos ou comentários.
- Seja autocontido: quem lê só o prompt precisa saber o que pesquisar e o que entregar.
- Escreva o prompt de forma clara e completa, para o agente acertar de primeira. Se o agente erra, ele volta à base e refaz a tarefa, o que demora e custa caro.

Formato (obrigatório):
- Responda só com as tarefas, uma por linha: [cpuN] [tarefaK] prompt.
- Ordem: cpu1 tarefa1, cpu1 tarefa2, cpu2 tarefa1, e assim por diante.
- Sem introdução, título, explicação, markdown ou bloco de código.

Exemplo BOM (pedido simples, certo):
Pedido: pesquisa 5 carros mais rápidos e 5 motos mais rápidas
[cpu1] [tarefa1] Use web_search para pesquisar os 5 carros mais rápidos. Traga em português.
[cpu2] [tarefa1] Use web_search para pesquisar as 5 motos mais rápidas. Traga em português.
Por que está certo: cada categoria pedida virou uma tarefa, sem ângulos extras. Como é pedido simples, usa 2 máquinas, uma por tarefa, e as duas rodam ao mesmo tempo. Cada prompt é curto e direto.

Exemplo RUIM (não faça assim):
Pedido: pesquisa 5 celulares mais bons para jogos; e tablets também
[cpu1] [tarefa1] Use web_search para pesquisar os 5 celulares mais seguros para jogar. Traga em português.
[cpu1] [tarefa2] Use web_search para pesquisar os 5 celulares mais rápidos para navegar em jogos. Traga em português.
[cpu1] [tarefa3] Use web_search para pesquisar os 5 celulares mais rápidos para café e jogos. Traga em português.
[cpu2] [tarefa1], [cpu2] [tarefa2] e [cpu2] [tarefa3]: os mesmos três ângulos, agora com tablets.
Por que está errado:
- Três tarefas na mesma máquina. O máximo é duas (tarefa1 e tarefa2).
- Os ângulos segurança, navegação e café não foram pedidos. O pedido era só celulares e tablets para jogos.
- Cada categoria foi quebrada em três tarefas. Bastava uma por categoria.
Certo seria:
[cpu1] [tarefa1] Use web_search para pesquisar os 5 celulares mais bons para jogos. Traga em português.
[cpu2] [tarefa1] Use web_search para pesquisar os 5 tablets mais bons para jogos. Traga em português.
"""

PADRAO_LINHA = re.compile(r"^\[cpu(\d+)\]\s*\[tarefa(\d+)\]\s*(\S.*)$", re.IGNORECASE)
PADRAO_ASPAS = re.compile(r'"([^"]{2,40})"')
PADRAO_MARCADOR = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")  # "- ", "* ", "1. ", "1) " no início


def montar_mensagens(pedido: str) -> list[dict]:
    pedido = pedido.strip()
    if not pedido:
        raise ValueError("o pedido está vazio")
    skill = (
        SKILL_PLANEJADOR
        .replace("__MAQ__", str(MAX_MAQUINAS))
        .replace("__POR__", str(MAX_POR_MAQUINA))
        .replace("__MAX__", str(MAX_TAREFAS))
    )
    return [
        {"role": "system", "content": skill},
        {"role": "user", "content": f"Pedido:\n{pedido}"},
    ]


def mensagem_de_correcao(erros: list[str]) -> str:
    problemas = "\n".join(f"- {e}" for e in erros)
    return (
        "Sua resposta não seguiu as regras. Problemas encontrados:\n"
        f"{problemas}\n\n"
        "Refaça a resposta inteira, somente com as tarefas no formato [cpuN] [tarefaK] prompt.\n"
        f"A numeração K recomeça em 1 em cada máquina, e cada máquina tem no máximo {MAX_POR_MAQUINA} tarefas. "
        "Use as máquinas em ordem (cpu1, depois cpu2, e assim por diante), sem pular nenhuma.\n"
        "NÃO invente nomes. Não crie ângulos extras nem cuidados de segurança. Sem texto extra."
    )


def extrair_resposta(saida: str):
    """Lê o bloco base64 que veio do Colab. Quebras de linha no meio não atrapalham."""
    m = re.search(r"^PLANO_B64_INICIO\s*$(.*?)^PLANO_B64_FIM\s*$", saida, re.M | re.S)
    if not m:
        return None
    corpo = "".join(m.group(1).split())
    if not corpo:
        return None
    try:
        return base64.b64decode(corpo).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


def _rotulo(cpu: int, k: int) -> str:
    return f"[cpu{cpu}] [tarefa{k}]"


def _normalizar(texto: str) -> str:
    return re.sub(r"\s+", " ", texto.lower()).strip()


def etiquetas_esperadas(total: int):
    """Etiquetas certas para N tarefas, na ordem de execução.

    1 tarefa: cpu1 tarefa1.
    2 a 4 tarefas (pedido simples): 2 máquinas, com as tarefas divididas.
        2 tarefas: cpu1 tarefa1, cpu2 tarefa1
        3 tarefas: cpu1 tarefa1 e tarefa2, cpu2 tarefa1
    5 ou mais: o mínimo de máquinas, com 2 tarefas em cada uma (a última pode ter 1).
    """
    if total <= 0:
        return []
    if total == 1:
        maquinas = 1
    elif total <= 4:
        maquinas = 2
    else:
        maquinas = -(-total // MAX_POR_MAQUINA)  # arredonda para cima
    base, sobra = divmod(total, maquinas)
    tamanhos = [base + 1] * sobra + [base] * (maquinas - sobra)
    return [(cpu, k) for cpu, tamanho in enumerate(tamanhos, start=1) for k in range(1, tamanho + 1)]


def validar_plano(texto: str, pedido: str = ""):
    """Devolve (plano, erros).

    plano = {cpu: [(k, prompt), ...]}, em ordem. k é a numeração dentro da máquina (1 ou 2).
    Use o plano só se a lista de erros estiver vazia.
    Se o pedido for dado e não tiver aspas, nomes entre aspas nas tarefas são tratados como inventados.
    """
    linhas = []
    for bruta in texto.splitlines():
        linha = PADRAO_MARCADOR.sub("", bruta.strip())
        if linha and not linha.startswith("```"):
            linhas.append(linha)

    erros = []
    recebidas = []  # (cpu, k, prompt) de cada linha que está no formato
    for numero, linha in enumerate(linhas, start=1):
        m = PADRAO_LINHA.match(linha)
        if not m:
            erros.append(f"linha {numero} fora do formato [cpuN] [tarefaK] prompt: {linha[:70]!r}")
            continue
        recebidas.append((int(m.group(1)), int(m.group(2)), m.group(3).strip()))

    if not recebidas:
        erros.append("nenhuma tarefa no formato [cpuN] [tarefaK] prompt")
        return {}, erros

    total = len(recebidas)
    if total > MAX_TAREFAS:
        erros.append(f"o máximo é {MAX_TAREFAS} tarefas; recebi {total}")

    # Cada etiqueta precisa existir: cpu de 1 a 5, e tarefa de 1 a 2 dentro da máquina
    for cpu, k, _ in recebidas:
        if not 1 <= cpu <= MAX_MAQUINAS:
            erros.append(f"{_rotulo(cpu, k)}: cpu{cpu} não existe; use só de cpu1 a cpu{MAX_MAQUINAS}")
        elif not 1 <= k <= MAX_POR_MAQUINA:
            erros.append(
                f"{_rotulo(cpu, k)}: a numeração recomeça em 1 em cada máquina; "
                f"cada máquina tem só tarefa1 e tarefa{MAX_POR_MAQUINA}"
            )

    # Nenhuma etiqueta pode aparecer duas vezes
    vistos = set()
    for cpu, k, _ in recebidas:
        if (cpu, k) in vistos:
            erros.append(f"{_rotulo(cpu, k)} aparece mais de uma vez")
        vistos.add((cpu, k))

    # As etiquetas precisam ser exatamente as esperadas para este número de tarefas
    if total <= MAX_TAREFAS:
        esperadas = etiquetas_esperadas(total)
        recebidas_etiquetas = [(cpu, k) for cpu, k, _ in recebidas]
        if sorted(recebidas_etiquetas) != sorted(esperadas):
            certas = ", ".join(_rotulo(cpu, k) for cpu, k in esperadas)
            erros.append(f"as etiquetas não batem com {total} tarefas. Use exatamente estas: {certas}")

    # Regras de cada prompt
    pedido_sem_aspas = bool(pedido.strip()) and '"' not in pedido
    pedido_lower = pedido.lower()
    for cpu, k, prompt in recebidas:
        rot = _rotulo(cpu, k)
        if len(prompt) < MIN_CARACTERES:
            erros.append(f"{rot}: prompt curto demais")
        if "web_search" not in prompt.lower():
            erros.append(f"{rot}: o prompt não manda usar web_search")
        if pedido_sem_aspas and PADRAO_ASPAS.search(prompt):
            erros.append(f"{rot}: colocou um nome entre aspas que o pedido não trouxe (nome inventado)")
        if pedido.strip():
            prompt_lower = prompt.lower()
            for palavra in PALAVRAS_EXTRAS:
                if palavra in prompt_lower and palavra not in pedido_lower:
                    erros.append(f"{rot}: acrescentou '{palavra}', que o pedido não trouxe")
                    break

    # Tarefas repetidas ou quase iguais
    for i in range(total):
        for j in range(i):
            cpu_a, k_a, prompt_a = recebidas[j]
            cpu_b, k_b, prompt_b = recebidas[i]
            a, b = _normalizar(prompt_a), _normalizar(prompt_b)
            if a == b:
                erros.append(f"{_rotulo(cpu_b, k_b)} repete exatamente {_rotulo(cpu_a, k_a)}")
            elif difflib.SequenceMatcher(None, a, b).ratio() >= LIMIAR_QUASE_IGUAL:
                erros.append(
                    f"{_rotulo(cpu_b, k_b)} é quase igual a {_rotulo(cpu_a, k_a)}; mude o ângulo da pesquisa"
                )

    plano = {}
    for cpu, k, prompt in sorted(recebidas, key=lambda item: (item[0], item[1])):
        if 1 <= cpu <= MAX_MAQUINAS and 1 <= k <= MAX_POR_MAQUINA:
            plano.setdefault(cpu, []).append((k, prompt))
    return plano, erros


def linhas_do_plano(plano: dict):
    """Devolve (cpu, k, prompt) na ordem de execução: cpu1 tarefa1, cpu1 tarefa2, cpu2 tarefa1..."""
    return [(cpu, k, prompt) for cpu in sorted(plano) for k, prompt in sorted(plano[cpu])]


if __name__ == "__main__":
    PEDIDO = "quero 5 plugins e 5 skills de navegação para o OpenClaw"
    angulos = [
        "um plugin para controlar o navegador no OpenClaw",
        "um plugin para ler e resumir páginas no OpenClaw",
        "um plugin para buscar e comparar resultados na web",
        "um plugin para gerenciar abas e sessões no OpenClaw",
        "um plugin para extrair texto estruturado de páginas",
        "uma skill para controlar o navegador no OpenClaw",
        "uma skill para ler e resumir páginas no OpenClaw",
        "uma skill para buscar e comparar resultados na web",
        "uma skill para gerenciar abas e sessões no OpenClaw",
        "uma skill para extrair texto estruturado de páginas",
    ]

    def linha(cpu, k, angulo):
        return (
            f"[cpu{cpu}] [tarefa{k}] Use web_search para pesquisar {angulo}. "
            "Traga o que faz e como instalar, em português."
        )

    # 3 tarefas: cpu1 com tarefa1 e tarefa2, cpu2 com tarefa1
    valido_3 = "\n".join([
        linha(1, 1, angulos[0]),
        linha(1, 2, angulos[1]),
        linha(2, 1, angulos[2]),
    ])
    # 10 tarefas: cpu1 a cpu5, cada uma com tarefa1 e tarefa2
    valido_10 = "\n".join(linha(i // 2 + 1, i % 2 + 1, angulos[i]) for i in range(10))
    # Numeração global, como era antes: tarefa3 e tarefa4 não existem dentro de cpu2
    numeracao_global = "\n".join([
        linha(1, 1, angulos[0]),
        linha(1, 2, angulos[1]),
        linha(2, 3, angulos[2]),
        linha(2, 4, angulos[3]),
    ])
    # Distribuição errada: para 3 tarefas o certo é cpu1 (2 tarefas) e cpu2 (1 tarefa)
    espalhado = "\n".join([
        linha(1, 1, angulos[0]),
        linha(2, 1, angulos[1]),
        linha(3, 1, angulos[2]),
    ])
    invalido = "\n".join([
        "Aqui estão as tarefas:",
        linha(1, 1, angulos[0]),
        linha(1, 2, angulos[1]),
        linha(1, 3, angulos[2]),
        '[cpu2] [tarefa1] Use web_search para pesquisar um plugin chamado "WebNav". Traga o que faz e como instalar, em português.',
        "[cpu9] [tarefa1] Use web_search para pesquisar algo sobre navegação no OpenClaw.",
    ])

    msgs = montar_mensagens(PEDIDO)
    for marca in ("__MAX__", "__POR__", "__MAQ__"):
        assert marca not in msgs[0]["content"], f"{marca} não foi trocado"
    print("montar_mensagens: OK")

    corpo = base64.b64encode(valido_3.encode("utf-8")).decode("ascii")
    saida = f"ruído do ssh\nPLANO_B64_INICIO\n{corpo[:60]}\n{corpo[60:]}\nPLANO_B64_FIM\n"
    assert extrair_resposta(saida) == valido_3, "extrair_resposta falhou"
    print("extrair_resposta: OK")

    for nome, texto in [("3 tarefas", valido_3), ("10 tarefas", valido_10)]:
        _, erros = validar_plano(texto, PEDIDO)
        print(f"{nome}: {'OK' if not erros else 'com erros'}")
        for erro in erros:
            print(f"   - {erro}")
        assert not erros, f"{nome} foi rejeitado"

    com_marcador = "\n".join("- " + l for l in valido_3.splitlines())
    _, erros = validar_plano(com_marcador, PEDIDO)
    assert not erros, f"marcadores de lista deveriam ser aceitos: {erros}"
    print("marcadores de lista: OK")

    plano3, _ = validar_plano(valido_3, PEDIDO)
    assert list(plano3) == [1, 2], "só cpu1 e cpu2 deveriam ser usadas"
    assert [k for k, _ in plano3[1]] == [1, 2]
    assert [k for k, _ in plano3[2]] == [1]
    plano10, _ = validar_plano(valido_10, PEDIDO)
    assert sorted(plano10) == [1, 2, 3, 4, 5]
    assert all([k for k, _ in itens] == [1, 2] for itens in plano10.values())
    ordem = [(cpu, k) for cpu, k, _ in linhas_do_plano(plano10)]
    assert ordem == [(c, k) for c in range(1, 6) for k in (1, 2)], ordem
    print("plano e ordem de execução: OK")

    _, erros = validar_plano(espalhado, PEDIDO)
    assert any("as etiquetas não batem com 3 tarefas" in e for e in erros), erros
    print("distribuição errada é detectada: OK")

    _, erros = validar_plano(numeracao_global, PEDIDO)
    assert any("a numeração recomeça" in e for e in erros), erros
    print("numeração global é rejeitada: OK")

    _, erros = validar_plano(invalido, PEDIDO)
    for esperado in ("fora do formato", "cpu9 não existe", "nome inventado", "as etiquetas não batem"):
        assert any(esperado in e for e in erros), f"não detectou: {esperado}"
    print("inválido: detectou os problemas")

    copia = linha(1, 1, angulos[0]) + "\n" + linha(1, 2, angulos[0])
    _, erros = validar_plano(copia, PEDIDO)
    assert any("repete exatamente" in e for e in erros), erros
    print("duplicatas: OK")

    com_seguranca = (
        linha(1, 1, angulos[0]).replace("Traga o que faz", "Traga cuidados de segurança e o que faz")
        + "\n" + linha(1, 2, angulos[1])
    )
    _, erros = validar_plano(com_seguranca, PEDIDO)
    assert any("acrescentou 'segurança'" in e for e in erros), erros
    print("cuidados de segurança não pedidos: OK")

    # Exemplos da skill: o bom passa e o ruim é rejeitado
    bom = "\n".join([
        "[cpu1] [tarefa1] Use web_search para pesquisar os 5 carros mais rápidos. Traga em português.",
        "[cpu2] [tarefa1] Use web_search para pesquisar as 5 motos mais rápidas. Traga em português.",
    ])
    plano_bom, erros = validar_plano(bom, "pesquisa 5 carros mais rápidos e 5 motos mais rápidas")
    assert not erros, erros
    assert [(cpu, k) for cpu, k, _ in linhas_do_plano(plano_bom)] == [(1, 1), (2, 1)]
    print("exemplo bom (2 tarefas, 2 máquinas): OK")

    ruim = "\n".join([
        "[cpu1] [tarefa1] Use web_search para pesquisar os 5 celulares mais seguros para jogar. Traga em português.",
        "[cpu1] [tarefa2] Use web_search para pesquisar os 5 celulares mais rápidos para navegar em jogos. Traga em português.",
        "[cpu1] [tarefa3] Use web_search para pesquisar os 5 celulares mais rápidos para café e jogos. Traga em português.",
        "[cpu2] [tarefa1] Use web_search para pesquisar os 5 tablets mais seguros para jogar. Traga em português.",
        "[cpu2] [tarefa2] Use web_search para pesquisar os 5 tablets mais rápidos para navegar em jogos. Traga em português.",
        "[cpu2] [tarefa3] Use web_search para pesquisar os 5 tablets mais rápidos para café e jogos. Traga em português.",
    ])
    _, erros = validar_plano(ruim, "pesquisa 5 celulares mais bons para jogos e tablets também")
    assert any("a numeração recomeça" in e for e in erros), erros
    assert any("acrescentou 'seguro'" in e for e in erros), erros
    print("exemplo ruim é rejeitado: OK")