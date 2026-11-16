package app.creatorhub.web;
import app.creatorhub.Nucleo;
import app.creatorhub.red.ClienteHub;
import android.net.Uri;
import android.webkit.WebResourceResponse;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Map;

/** Ejecuta el ProxyHub de produccion; dobles limitados a Android/transporte/disco, sin red ni credenciales. */
public final class PruebaProxyImagenes {
    private static final String RUTA="/img/v/123456789?v=aaaaaaaa&t=md";
    private static final ArrayList<String> fallos=new ArrayList<>();
    private static void comprobar(boolean ok,String m) { if(!ok) fallos.add(m); }
    private static WebResourceResponse pedir(Nucleo n,String ruta) { return new ProxyHub(n).atender("GET",Uri.parse("https://appassets.androidplatform.net"+ruta)); }
    private static Nucleo nucleo(int status,String etag) {
        Nucleo n=new Nucleo();
        n.cliente.respuesta=new ClienteHub.Respuesta(status,"image/webp","RED".getBytes(StandardCharsets.UTF_8),
                etag==null?Map.of("Cache-Control","private, no-store"):Map.of("Cache-Control","private, no-store","ETag",etag));
        return n;
    }
    public static void main(String[] args) throws Exception {
        Nucleo mismatch=nucleo(200,"\"bbbbbbbb-md\"");
        WebResourceResponse r=pedir(mismatch,RUTA);
        comprobar(mismatch.copia.imagenEnCache(RUTA)==null,"ETag distinto no debe persistir bajo v anterior");
        comprobar(r.headers.get("Cache-Control").contains("no-store"),"HTTP respeta no-store en mismatch");
        Nucleo valida=nucleo(200,"\"aaaaaaaa-md\"");
        r=pedir(valida,RUTA);
        comprobar(valida.copia.imagenEnCache(RUTA)!=null,"Imagen verificada conserva almacenamiento offline privado");
        comprobar(r.headers.get("Cache-Control").contains("no-store"),"HTTP verificado tambien respeta no-store");
        Nucleo sinEtag=nucleo(200,null);pedir(sinEtag,RUTA);
        comprobar(sinEtag.copia.imagenEnCache(RUTA)==null,"Sin ETag no debe persistir");
        Nucleo cero=nucleo(200,"\"aaaaaaaa-md\"");r=pedir(cero,"/img/v/123456789?v=0&t=md");
        comprobar(cero.copia.cache.isEmpty()&&r.headers.get("Cache-Control").contains("no-store"),"v0 no persiste ni cambia no-store");
        for(int status:new int[]{404,429,503}) {
            Nucleo fallo=nucleo(status,null);
            fallo.copia.guardarImagen("/img/v/123456789?v=aaaaaaaa&t=sm","SM-CORRECTA".getBytes(StandardCharsets.UTF_8));
            r=pedir(fallo,RUTA);
            comprobar(r.status==200&&new String(r.body.readAllBytes(),StandardCharsets.UTF_8).equals("SM-CORRECTA"),"MD "+status+" usa SM de misma ID/version");
            comprobar(r.headers.get("Cache-Control").contains("no-store"),"Fallback privado no abre cache HTTP");
        }
        for(String ajena:new String[]{"/img/v/123456789?v=bbbbbbbb&t=sm","/img/v/999999999?v=aaaaaaaa&t=sm"}) {
            Nucleo n=nucleo(503,null);n.copia.guardarImagen(ajena,"AJENA".getBytes(StandardCharsets.UTF_8));
            comprobar(pedir(n,RUTA).status==503,"Nunca usar otra ID o version");
        }
        Nucleo noAutorizada=nucleo(401,null);noAutorizada.copia.guardarImagen("/img/v/123456789?v=aaaaaaaa&t=sm",new byte[]{1});
        comprobar(pedir(noAutorizada,RUTA).status==401,"401 debe pedir acceso, no ocultarse con fallback");
        Nucleo disco=nucleo(200,"\"aaaaaaaa-md\"");disco.copia.guardarImagen(RUTA,new byte[]{1});r=pedir(disco,RUTA);
        comprobar(r.headers.get("Cache-Control").contains("no-store"),"Archivo privado tambien no-store HTTP");
        if(!fallos.isEmpty()) { for(String f:fallos) System.out.println("FAIL: "+f); throw new AssertionError(fallos.size()+" regresiones de cache"); }
        System.out.println("PASS: ProxyHub real, versiones/ETag/no-store, fallback 404/429/503 y aislamiento ID/version/401.");
    }
}
