package app.creatorhub.red;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Lector JSON mínimo SOLO para las pruebas en el JDK (en Android se usa org.json). Objetos, listas, texto, enteros, bool, null. */
final class MiniJson {
    private final String s;
    private int i;

    private MiniJson(String s) { this.s = s; }

    static Object leer(String texto) {
        MiniJson p = new MiniJson(texto);
        Object v = p.valor();
        p.espacios();
        if (p.i != p.s.length()) throw new IllegalArgumentException("JSON: sobra texto en " + p.i);
        return v;
    }

    @SuppressWarnings("unchecked")
    static Map<String, Object> obj(Object o) { return (Map<String, Object>) o; }

    @SuppressWarnings("unchecked")
    static List<Object> lista(Object o) { return (List<Object>) o; }

    private void espacios() { while (i < s.length() && Character.isWhitespace(s.charAt(i))) i++; }

    private Object valor() {
        espacios();
        char c = s.charAt(i);
        if (c == '{') {
            Map<String, Object> m = new LinkedHashMap<>();
            i++; espacios();
            if (s.charAt(i) == '}') { i++; return m; }
            while (true) {
                espacios();
                String k = texto();
                espacios(); esperar(':');
                m.put(k, valor());
                espacios();
                if (s.charAt(i) == ',') { i++; continue; }
                esperar('}');
                return m;
            }
        }
        if (c == '[') {
            List<Object> l = new ArrayList<>();
            i++; espacios();
            if (s.charAt(i) == ']') { i++; return l; }
            while (true) {
                l.add(valor());
                espacios();
                if (s.charAt(i) == ',') { i++; continue; }
                esperar(']');
                return l;
            }
        }
        if (c == '"') return texto();
        if (s.startsWith("true", i)) { i += 4; return Boolean.TRUE; }
        if (s.startsWith("false", i)) { i += 5; return Boolean.FALSE; }
        if (s.startsWith("null", i)) { i += 4; return null; }
        int ini = i;
        while (i < s.length() && "-+0123456789.eE".indexOf(s.charAt(i)) >= 0) i++;
        String num = s.substring(ini, i);
        if (num.isEmpty()) throw new IllegalArgumentException("JSON: valor inesperado en " + ini);
        return num.matches("-?\\d+") ? (Object) Long.parseLong(num) : (Object) Double.parseDouble(num);
    }

    private void esperar(char c) {
        if (s.charAt(i) != c) throw new IllegalArgumentException("JSON: se esperaba '" + c + "' en " + i);
        i++;
    }

    private String texto() {
        esperar('"');
        StringBuilder sb = new StringBuilder();
        while (true) {
            char c = s.charAt(i++);
            if (c == '"') return sb.toString();
            if (c != '\\') { sb.append(c); continue; }
            char e = s.charAt(i++);
            switch (e) {
                case '"': sb.append('"'); break;
                case '\\': sb.append('\\'); break;
                case '/': sb.append('/'); break;
                case 'b': sb.append('\b'); break;
                case 'f': sb.append('\f'); break;
                case 'n': sb.append('\n'); break;
                case 'r': sb.append('\r'); break;
                case 't': sb.append('\t'); break;
                case 'u': sb.append((char) Integer.parseInt(s.substring(i, i + 4), 16)); i += 4; break;
                default: throw new IllegalArgumentException("JSON: escape inválido en " + i);
            }
        }
    }
}
