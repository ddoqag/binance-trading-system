package plugin;

import java.net.URL;
import java.net.URLClassLoader;
import java.nio.file.Path;

public class PluginClassLoader extends URLClassLoader {
    public PluginClassLoader(URL[] urls, ClassLoader parent){super(urls,parent);}
    public void closeLoader(){try{super.close();}catch (Exception e){}}
    public static PluginClassLoader create(Path jar) throws Exception{
        return new PluginClassLoader(new URL[]{jar.toUri().toURL()},ClassLoader.getSystemClassLoader());
    }
}
