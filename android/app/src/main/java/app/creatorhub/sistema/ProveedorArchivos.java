package app.creatorhub.sistema;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import java.io.File;
import java.io.FileNotFoundException;
import java.io.FileOutputStream;
import java.io.IOException;
import java.util.Locale;
import java.util.regex.Pattern;

/**
 * ContentProvider propio para compartir una imagen o un CSV/JSON (C21) sin FileProvider de AndroidX:
 * `content://<applicationId>.archivos/<nombre>`, solo lectura, `exported=false` + `grantUriPermissions` (la app que
 * recibe el ACTION_SEND solo lee lo que se le concedió). Los archivos viven en `files/compartir/` y se borran al día.
 */
public final class ProveedorArchivos extends ContentProvider {
    private static final Pattern NOMBRE = Pattern.compile("[A-Za-z0-9._ -]{1,100}");
    private static final long VIGENCIA_MS = 24L * 3600 * 1000;

    public static String autoridad(Context ctx) { return ctx.getPackageName() + ".archivos"; }

    static File carpeta(Context ctx) { return new File(ctx.getFilesDir(), "compartir"); }

    /** Nombre seguro para el archivo compartido (sin rutas, sin caracteres raros, con extensión). */
    public static String nombreSeguro(String nombre, String extension) {
        String n = nombre == null ? "" : nombre.replaceAll("[^A-Za-z0-9._ -]", "_").trim();
        if (n.startsWith(".")) n = "_" + n;
        if (n.isEmpty()) n = "corte";
        if (n.length() > 80) n = n.substring(0, 80);
        if (!n.toLowerCase(Locale.ROOT).endsWith("." + extension)) n = n + "." + extension;
        return n;
    }

    /** Escribe `datos` en files/compartir/<nombre> y devuelve su content:// para el Intent. */
    public static Uri publicar(Context ctx, String nombre, byte[] datos) throws IOException {
        File dir = carpeta(ctx);
        if (!dir.isDirectory() && !dir.mkdirs()) throw new IOException("sin carpeta");
        limpiarViejos(dir);
        if (!NOMBRE.matcher(nombre).matches()) throw new IOException("nombre inválido");
        File f = new File(dir, nombre);
        try (FileOutputStream os = new FileOutputStream(f)) {
            os.write(datos);
            os.getFD().sync();
        }
        return new Uri.Builder().scheme("content").authority(autoridad(ctx)).appendPath(nombre).build();
    }

    private static void limpiarViejos(File dir) {
        File[] fs = dir.listFiles();
        if (fs == null) return;
        long limite = System.currentTimeMillis() - VIGENCIA_MS;
        for (File f : fs) if (f.lastModified() < limite && !f.delete()) f.deleteOnExit();
    }

    private File archivoDe(Uri uri) throws FileNotFoundException {
        Context ctx = getContext();
        if (ctx == null || uri == null || !autoridad(ctx).equals(uri.getAuthority())) throw new FileNotFoundException();
        if (uri.getPathSegments().size() != 1) throw new FileNotFoundException();
        String nombre = uri.getLastPathSegment();
        if (nombre == null || !NOMBRE.matcher(nombre).matches() || nombre.startsWith(".")) throw new FileNotFoundException();
        File dir = carpeta(ctx);
        File f = new File(dir, nombre);
        try {
            if (!f.getCanonicalFile().getParentFile().equals(dir.getCanonicalFile())) throw new FileNotFoundException();
        } catch (IOException e) {
            throw new FileNotFoundException();
        }
        if (!f.isFile()) throw new FileNotFoundException();
        return f;
    }

    @Override public boolean onCreate() { return true; }

    @Override public Cursor query(Uri uri, String[] proyeccion, String seleccion, String[] args, String orden) {
        File f;
        try { f = archivoDe(uri); } catch (FileNotFoundException e) { return null; }
        String[] cols = proyeccion != null ? proyeccion : new String[] {OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE};
        MatrixCursor c = new MatrixCursor(cols, 1);
        Object[] fila = new Object[cols.length];
        for (int i = 0; i < cols.length; i++) {
            if (OpenableColumns.DISPLAY_NAME.equals(cols[i])) fila[i] = f.getName();
            else if (OpenableColumns.SIZE.equals(cols[i])) fila[i] = f.length();
        }
        c.addRow(fila);
        return c;
    }

    @Override public String getType(Uri uri) {
        String n = uri == null ? null : uri.getLastPathSegment();
        if (n == null) return null;
        String e = n.substring(n.lastIndexOf('.') + 1).toLowerCase(Locale.ROOT);
        switch (e) {
            case "csv": return "text/csv";
            case "json": return "application/json";
            case "webp": return "image/webp";
            case "jpg": case "jpeg": return "image/jpeg";
            case "png": return "image/png";
            case "gif": return "image/gif";
            case "avif": return "image/avif";
            default: return "application/octet-stream";
        }
    }

    @Override public ParcelFileDescriptor openFile(Uri uri, String modo) throws FileNotFoundException {
        if (modo == null || !"r".equals(modo)) throw new FileNotFoundException("solo lectura");
        return ParcelFileDescriptor.open(archivoDe(uri), ParcelFileDescriptor.MODE_READ_ONLY);
    }

    @Override public Uri insert(Uri uri, ContentValues valores) { throw new UnsupportedOperationException("solo lectura"); }

    @Override public int delete(Uri uri, String seleccion, String[] args) { return 0; }

    @Override public int update(Uri uri, ContentValues valores, String seleccion, String[] args) { return 0; }
}
