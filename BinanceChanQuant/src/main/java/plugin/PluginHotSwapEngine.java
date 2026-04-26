package plugin;

import selector.StrategySelector;
import java.nio.file.*;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

public class PluginHotSwapEngine {
    private static final String DIR = "plugins";
    private final StrategySelector selector;
    private final ScheduledExecutorService pool = Executors.newSingleThreadScheduledExecutor();

    public PluginHotSwapEngine(StrategySelector selector){
        this.selector=selector;
        initDir();
        startScan();
    }

    private void initDir(){
        Path p = Paths.get(DIR);
        if(!Files.exists(p)) try{Files.createDirectories(p);}catch (Exception e){}
    }

    private void startScan(){
        pool.scheduleAtFixedRate(this::loadPlugins,5,5, TimeUnit.SECONDS);
    }

    private void loadPlugins(){
        try{
            Files.list(Paths.get(DIR)).filter(Files::isRegularFile)
                    .filter(p->p.toString().endsWith(".jar"))
                    .forEach(this::loadJar);
        }catch (Exception e){}
    }

    private void loadJar(Path jar){
        try{
            PluginClassLoader loader = PluginClassLoader.create(jar);
            Class<?> clz = loader.loadClass("ChanTrendStrategyPlugin");
            StrategyPlugin sp = (StrategyPlugin)clz.getDeclaredConstructor().newInstance();
            selector.registerStrategy(sp);
            System.out.println("加载策略插件："+sp.getStrategyName());
        }catch (Exception e){}
    }

    public void shutdown(){pool.shutdown();}
}
