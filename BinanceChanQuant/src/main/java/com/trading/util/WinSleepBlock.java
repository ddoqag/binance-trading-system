package com.trading.util;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;

/**
 * Prevents Windows system sleep during trading system operation.
 * Uses SetThreadExecutionState via PowerShell — zero external dependencies.
 */
public final class WinSleepBlock {

    private static volatile boolean active = false;

    static {
        try {
            Process p = Runtime.getRuntime().exec(new String[]{
                "powershell.exe", "-NoProfile", "-Command",
                "Add-Type -TypeDefinition @' "
                    + "using System; "
                    + "using System.Runtime.InteropServices; "
                    + "public class K { "
                        + "[DllImport(\"kernel32.dll\")] "
                        + "public static extern int SetThreadExecutionState(int f); "
                    + "} '@; "
                    + "[K]::SetThreadExecutionState(0x80000000); "
                    + "exit 0"
            });
            active = (p.waitFor() == 0);
        } catch (Exception e) {
            active = false;
        }
    }

    private WinSleepBlock() {}

    /**
     * Keep system awake, allow screen to turn off.
     */
    public static void keepSystemRunning() {
        if (!active) return;
        exec(0x80000003); // ES_CONTINUOUS | ES_SYSTEM_REQUIRED
    }

    /**
     * Keep system awake and prevent screen dimming/off.
     */
    public static void keepSystemAndScreen() {
        if (!active) return;
        exec(0x80000007); // ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
    }

    /**
     * Restore normal Windows sleep behavior.
     */
    public static void restoreSleep() {
        if (!active) return;
        exec(0x80000000); // ES_CONTINUOUS only
    }

    private static void exec(int flags) {
        try {
            Runtime.getRuntime().exec(new String[]{
                "powershell.exe", "-NoProfile", "-Command",
                "Add-Type -TypeDefinition @' "
                    + "using System; "
                    + "using System.Runtime.InteropServices; "
                    + "public class K { "
                        + "[DllImport(\"kernel32.dll\")] "
                        + "public static extern int SetThreadExecutionState(int f); "
                    + "} '@; "
                    + "[K]::SetThreadExecutionState(0x"
                    + Integer.toHexString(flags)
                    + ")"
            });
        } catch (IOException ignored) {}
    }

    /** @return true if sleep blocker is functional */
    public static boolean isActive() {
        return active;
    }
}
