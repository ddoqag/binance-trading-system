package config;

import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.Properties;

public class ConfigUtil {
    private static final Properties prop = new Properties();

    static {
        try (InputStream is = ConfigUtil.class.getClassLoader().getResourceAsStream("config.properties")) {
            prop.load(new InputStreamReader(is, StandardCharsets.UTF_8));
        } catch (IOException e) {
            e.printStackTrace();
        }
    }

    public static String get(String key) {
        return prop.getProperty(key);
    }

    public static int getInt(String key) {
        return Integer.parseInt(get(key));
    }

    public static double getDouble(String key) {
        return Double.parseDouble(get(key));
    }

    public static boolean isTestNet() {
        return "true".equalsIgnoreCase(get("testnet"));
    }

    public static String get(String key, String defaultValue) {
        return prop.getProperty(key, defaultValue);
    }
}
