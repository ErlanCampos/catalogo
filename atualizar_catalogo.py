#!/usr/bin/env python3
"""
Atualiza o produtos-roland.js lendo TODAS as páginas da marca Roland
(inclusive os itens INDISPONÍVEIS), baixando fotos e extraindo Part Number.
"""
import csv, html, json, os, re, shutil, sys, time, urllib.request
from playwright.sync_api import sync_playwright

BASE = "https://www.spplotter.com.br/"
URL_MARCA = BASE + "marca/roland.html"
CDN = "https://cdn.awsli.com.br/{size}/423/423318/produto/"
ARQ = "produtos-roland.js"
ROW = re.compile(r'\["(.*?)","(.*?)",([\d.]+),"(.*?)","(.*?)","(.*?)"\]')

# Procura estritamente por Part Number ou P/N
PN = re.compile(r"(?:Part\s*Number|P/N)[\s:–-]{0,8}((?=[\w\-/.]*\d)[\w\-/.]{4,})", re.I)
CP = re.compile(r"Compatibilidades?\s*:[ \t]*(.+)", re.I)

def baixar(url, binario=False):
    req = urllib.request.Request(urllib.request.quote(url, safe=":/?=&%"), headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    })
    with urllib.request.urlopen(req, timeout=40) as r:
        dados = r.read()
    return dados if binario else dados.decode("utf-8", "replace")

def foto(img, slug):
    if not img:
        return ""
    # Se a imagem já estiver no formato local "imagens/..."
    if img.startswith("imagens/"):
        return img
        
    os.makedirs("imagens", exist_ok=True)
    ext = os.path.splitext(img)[1].lower() or ".jpg"
    nome = re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-") + ext
    destino = os.path.join("imagens", nome)
    
    # Se a imagem não existe ou está vazia (0 bytes), baixa de novo
    if not os.path.exists(destino) or os.path.getsize(destino) == 0:
        for tam in ("600x600", "300x300"):
            try:
                url_img = CDN.format(size=tam) + img
                dados = baixar(url_img, True)
                if dados:
                    open(destino, "wb").write(dados)
                    break
            except Exception:
                continue
        else:
            # Se falhar tudo, retorna o link original do CDN
            return CDN.format(size="300x300") + img
            
    return "imagens/" + nome

def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if not os.path.exists(ARQ):
        sys.exit(f"Não achei o arquivo {ARQ} nesta pasta.")

    fonte = open(ARQ, encoding="utf-8").read()
    linhas_antigas = ROW.findall(fonte)
    if not linhas_antigas:
        sys.exit("Não encontrei os itens em " + ARQ)

    shutil.copy(ARQ, ARQ + ".bak")
    slugs_existentes = {r[4] for r in linhas_antigas}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # 1. PERCORRE TODAS AS PÁGINAS DA MARCA ROLAND (?pagina=1, ?pagina=2...)
        print("Buscando produtos em todas as páginas da marca Roland...")
        todos_os_slugs = []
        pagina = 1

        while True:
            url_lista = f"{URL_MARCA}?pagina={pagina}"
            page.goto(url_lista, wait_until="domcontentloaded", timeout=60000)
            
            try:
                page.wait_for_selector("a.produto-sobrepor", timeout=5000)
            except:
                break # Se não achou produtos, chegou ao fim

            cards = page.query_selector_all("a.produto-sobrepor")
            if not cards:
                break

            print(f" -> Página {pagina}: {len(cards)} produtos encontrados.")
            for card in cards:
                slug = card.get_attribute("href").split("/")[-1]
                if slug:
                    todos_os_slugs.append(slug)

            pagina += 1
            time.sleep(0.5)

        # Remove duplicatas, mantendo a ordem
        todos_os_slugs = list(dict.fromkeys(todos_os_slugs))
        print(f"Total de produtos encontrados no site: {len(todos_os_slugs)}")

        # 2. IDENTIFICA OS NOVOS SLUGS
        novos_slugs = [s for s in todos_os_slugs if s not in slugs_existentes]
        print(f"Itens novos/indisponíveis para adicionar: {len(novos_slugs)}")

        # 3. JUNTA A LISTA ANTIGA COM OS NOVOS
        todos_para_processar = []
        for r in linhas_antigas:
            todos_para_processar.append({
                "nome": r[1], "preco": r[2], "img": r[3], "slug": r[4]
            })

        for slug in novos_slugs:
            todos_para_processar.append({
                "nome": "", "preco": 0, "img": "", "slug": slug
            })

        # 4. VISITA CADA PRODUTO PARA EXTRAIR DADOS E BAIXAR IMAGEM
        print(f"Processando {len(todos_para_processar)} produtos...")
        novos_dados, sem_pn, sem_cp, rel = [], [], [], []

        for n, item in enumerate(todos_para_processar, 1):
            nome, preco, img, slug = item["nome"], item["preco"], item["img"], item["slug"]
            pn = cp = ""
            trecho = ""
            url_produto = BASE + slug

            try:
                page.goto(url_produto, wait_until="domcontentloaded", timeout=30000)
                try:
                    page.wait_for_selector("#descricao, .descricao, .board_htm", timeout=3000)
                except:
                    page.wait_for_timeout(1000)

                texto = page.inner_text("body")

                # Extrai compatibilidade
                cp_match = CP.search(texto)
                if cp_match:
                    cp = re.split(r"(?:Part\s*Number|P/N)", cp_match.group(1), flags=re.I)[0].strip(" -–:")

                # Extrai Part Number (se não achar, fica vazio)
                pn_match = PN.search(texto)
                if pn_match:
                    pn = pn_match.group(1).strip(".-/")
                    trecho = re.sub(r"\s+", " ", texto[max(0, pn_match.start() - 20): pn_match.end() + 40])
                else:
                    trecho = "(não achei 'Part Number' na página)"

                # Se nome/preço/imagem estiverem vazios (itens novos), pega da página do produto
                if not nome:
                    try:
                        nome_el = page.query_selector("h1.nome-produto")
                        if nome_el:
                            nome = nome_el.inner_text().strip()
                    except:
                        pass
                if not preco or preco == 0:
                    try:
                        preco_el = page.query_selector(".preco-promocional, .preco-venda")
                        if preco_el:
                            preco_txt = preco_el.inner_text().replace("R$", "").replace(".", "").replace(",", ".").strip()
                            preco = float(preco_txt)
                    except:
                        preco = 0
                if not img:
                    try:
                        img_el = page.query_selector("#imagemProduto")
                        if img_el:
                            img_url = img_el.get_attribute("src")
                            # CORREÇÃO AQUI: pega o caminho depois de /produto/ (ex: 57148179/1ad039558f.jpg)
                            match = re.search(r'/produto/(.+)$', img_url)
                            if match:
                                img = match.group(1)
                            else:
                                img = img_url.split("/")[-1]
                    except:
                        pass

            except Exception as e:
                print(f"[{n}/{len(todos_para_processar)}] ERRO em {nome or slug}: {e}")
                trecho = f"ERRO: {e}"

            print(f"[{n}/{len(todos_para_processar)}] Cód: {pn or '(Vazio)'} | {nome or slug}")

            if not pn:
                sem_pn.append(nome or slug)
            if not cp:
                sem_cp.append(nome or slug)

            rel.append((nome or slug, url_produto, pn, cp, trecho))

            # Baixa a imagem (agora com a URL correta)
            img_destino = foto(img, slug) if img else ""

            novos_dados.append((pn, nome or slug, preco, img_destino, slug, cp))
            time.sleep(0.3)

        browser.close()

    # 5. GERA O NOVO ARQUIVO JS
    def linha(r):
        return "[%s,%s,%s,%s,%s,%s]" % (json.dumps(r[0], ensure_ascii=False), json.dumps(r[1], ensure_ascii=False),
               r[2], json.dumps(r[3], ensure_ascii=False), json.dumps(r[4], ensure_ascii=False), json.dumps(r[5], ensure_ascii=False))

    corpo = ",\n".join(linha(r) for r in novos_dados)
    i = fonte.index("const ITENS_ROLAND = [") + len("const ITENS_ROLAND = [")
    j = fonte.index("].map(")
    open(ARQ, "w", encoding="utf-8").write(fonte[:i] + "\n" + corpo + "\n" + fonte[j:])

    # 6. GERA O RELATÓRIO CSV
    with open("relatorio_catalogo.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["item", "link", "part_number", "compatibilidade", "trecho_da_pagina"])
        w.writerows(rel)

    print(f"\nPronto! Catálogo atualizado com {len(novos_dados)} itens.")
    print(f"Itens que ficaram sem código: {len(sem_pn)}")
    print("Abra o relatorio_catalogo.csv para conferir.")

if __name__ == "__main__":
    main()