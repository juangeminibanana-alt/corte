#include "win32_window.h"

#include <dwmapi.h>
#include <flutter_windows.h>

#include <algorithm>

#include "resource.h"

namespace {

/// Window attribute that enables dark mode window decorations.
///
/// Redefined in case the developer's machine has a Windows SDK older than
/// version 10.0.22000.0.
/// See: https://docs.microsoft.com/windows/win32/api/dwmapi/ne-dwmapi-dwmwindowattribute
#ifndef DWMWA_USE_IMMERSIVE_DARK_MODE
#define DWMWA_USE_IMMERSIVE_DARK_MODE 20
#endif

constexpr const wchar_t kWindowClassName[] = L"FLUTTER_RUNNER_WIN32_WINDOW";

/// Registry key for app theme preference.
///
/// A value of 0 indicates apps should use dark mode. A non-zero or missing
/// value indicates apps should use light mode.
constexpr const wchar_t kGetPreferredBrightnessRegKey[] =
  L"Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize";
constexpr const wchar_t kGetPreferredBrightnessRegValue[] = L"AppsUseLightTheme";

// The number of Win32Window objects that currently exist.
static int g_active_window_count = 0;

using EnableNonClientDpiScaling = BOOL __stdcall(HWND hwnd);

// Scale helper to convert logical scaler values to physical using passed in
// scale factor
int Scale(int source, double scale_factor) {
  return static_cast<int>(source * scale_factor);
}

// Return usable physical bounds, respecting taskbars and monitors that start
// at a negative virtual-screen coordinate. No process/system DPI setting is
// changed: the existing runner converts DIP values exactly once.
bool WorkspaceBounds(HMONITOR monitor, double scale_factor, RECT* bounds) {
  MONITORINFO information{};
  information.cbSize = static_cast<DWORD>(sizeof(information));
  RECT work{};
  if (GetMonitorInfo(monitor, &information)) {
    work = information.rcWork;
  } else if (!SystemParametersInfo(SPI_GETWORKAREA, 0, &work, 0)) {
    return false;
  }

  const int width = static_cast<int>(work.right - work.left);
  const int height = static_cast<int>(work.bottom - work.top);
  if (width <= 0 || height <= 0) {
    return false;
  }
  const int margin = Scale(24, scale_factor);
  const int horizontal_margin = (std::min)(margin, (width - 1) / 2);
  const int vertical_margin = (std::min)(margin, (height - 1) / 2);
  *bounds = RECT{work.left + horizontal_margin, work.top + vertical_margin,
                 work.right - horizontal_margin,
                 work.bottom - vertical_margin};
  return true;
}

double MonitorScale(HMONITOR monitor) {
  const UINT dpi = FlutterDesktopGetDpiForMonitor(monitor);
  return static_cast<double>(dpi == 0 ? 96 : dpi) / 96.0;
}

// Dynamically loads the |EnableNonClientDpiScaling| from the User32 module.
// This API is only needed for PerMonitor V1 awareness mode.
void EnableFullDpiSupportIfAvailable(HWND hwnd) {
  HMODULE user32_module = LoadLibraryA("User32.dll");
  if (!user32_module) {
    return;
  }
  auto enable_non_client_dpi_scaling =
      reinterpret_cast<EnableNonClientDpiScaling*>(
          GetProcAddress(user32_module, "EnableNonClientDpiScaling"));
  if (enable_non_client_dpi_scaling != nullptr) {
    enable_non_client_dpi_scaling(hwnd);
  }
  FreeLibrary(user32_module);
}

}  // namespace

// Manages the Win32Window's window class registration.
class WindowClassRegistrar {
 public:
  ~WindowClassRegistrar() = default;

  // Returns the singleton registrar instance.
  static WindowClassRegistrar* GetInstance() {
    if (!instance_) {
      instance_ = new WindowClassRegistrar();
    }
    return instance_;
  }

  // Returns the name of the window class, registering the class if it hasn't
  // previously been registered.
  const wchar_t* GetWindowClass();

  // Unregisters the window class. Should only be called if there are no
  // instances of the window.
  void UnregisterWindowClass();

 private:
  WindowClassRegistrar() = default;

  static WindowClassRegistrar* instance_;

  bool class_registered_ = false;
};

WindowClassRegistrar* WindowClassRegistrar::instance_ = nullptr;

const wchar_t* WindowClassRegistrar::GetWindowClass() {
  if (!class_registered_) {
    WNDCLASS window_class{};
    window_class.hCursor = LoadCursor(nullptr, IDC_ARROW);
    window_class.lpszClassName = kWindowClassName;
    window_class.style = CS_HREDRAW | CS_VREDRAW;
    window_class.cbClsExtra = 0;
    window_class.cbWndExtra = 0;
    window_class.hInstance = GetModuleHandle(nullptr);
    window_class.hIcon =
        LoadIcon(window_class.hInstance, MAKEINTRESOURCE(IDI_APP_ICON));
    window_class.hbrBackground = 0;
    window_class.lpszMenuName = nullptr;
    window_class.lpfnWndProc = Win32Window::WndProc;
    RegisterClass(&window_class);
    class_registered_ = true;
  }
  return kWindowClassName;
}

void WindowClassRegistrar::UnregisterWindowClass() {
  UnregisterClass(kWindowClassName, nullptr);
  class_registered_ = false;
}

Win32Window::Win32Window() {
  ++g_active_window_count;
}

Win32Window::~Win32Window() {
  --g_active_window_count;
  Destroy();
}

bool Win32Window::Create(const std::wstring& title,
                         const Point& origin,
                         const Size& size) {
  Destroy();

  const wchar_t* window_class =
      WindowClassRegistrar::GetInstance()->GetWindowClass();

  const POINT target_point = {static_cast<LONG>(origin.x),
                              static_cast<LONG>(origin.y)};
  HMONITOR monitor = MonitorFromPoint(target_point, MONITOR_DEFAULTTONEAREST);
  const double scale_factor = MonitorScale(monitor);
  int width = Scale(static_cast<int>(size.width), scale_factor);
  int height = Scale(static_cast<int>(size.height), scale_factor);
  int left = Scale(static_cast<int>(origin.x), scale_factor);
  int top = Scale(static_cast<int>(origin.y), scale_factor);
  RECT bounds{};
  if (WorkspaceBounds(monitor, scale_factor, &bounds)) {
    const int available_width = static_cast<int>(bounds.right - bounds.left);
    const int available_height = static_cast<int>(bounds.bottom - bounds.top);
    width = (std::min)(width, available_width);
    height = (std::min)(height, available_height);
    left = static_cast<int>(bounds.left) + (available_width - width) / 2;
    top = static_cast<int>(bounds.top) + (available_height - height) / 2;
  }

  HWND window = CreateWindow(
      window_class, title.c_str(), WS_OVERLAPPEDWINDOW, left, top, width, height,
      nullptr, nullptr, GetModuleHandle(nullptr), this);

  if (!window) {
    return false;
  }

  UpdateTheme(window);

  return OnCreate();
}

bool Win32Window::Show() {
  return ShowWindow(window_handle_, SW_SHOWNORMAL);
}

// static
LRESULT CALLBACK Win32Window::WndProc(HWND const window,
                                      UINT const message,
                                      WPARAM const wparam,
                                      LPARAM const lparam) noexcept {
  if (message == WM_NCCREATE) {
    auto window_struct = reinterpret_cast<CREATESTRUCT*>(lparam);
    SetWindowLongPtr(window, GWLP_USERDATA,
                     reinterpret_cast<LONG_PTR>(window_struct->lpCreateParams));

    auto that = static_cast<Win32Window*>(window_struct->lpCreateParams);
    EnableFullDpiSupportIfAvailable(window);
    that->window_handle_ = window;
  } else if (Win32Window* that = GetThisFromHandle(window)) {
    return that->MessageHandler(window, message, wparam, lparam);
  }

  return DefWindowProc(window, message, wparam, lparam);
}

LRESULT
Win32Window::MessageHandler(HWND hwnd,
                            UINT const message,
                            WPARAM const wparam,
                            LPARAM const lparam) noexcept {
  switch (message) {
    case WM_GETMINMAXINFO: {
      auto limits = reinterpret_cast<MINMAXINFO*>(lparam);
      HMONITOR monitor = MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST);
      const double scale_factor = MonitorScale(monitor);
      RECT bounds{};
      if (limits != nullptr && WorkspaceBounds(monitor, scale_factor, &bounds)) {
        const int available_width = static_cast<int>(bounds.right - bounds.left);
        const int available_height = static_cast<int>(bounds.bottom - bounds.top);
        limits->ptMinTrackSize.x =
            (std::min)(Scale(960, scale_factor), available_width);
        limits->ptMinTrackSize.y =
            (std::min)(Scale(620, scale_factor), available_height);
        // Leave maximized position/size and maximum tracking bounds to Windows
        // so maximize, Snap and cross-monitor movement keep their OS behavior.
        return 0;
      }
      break;
    }

    case WM_DESTROY:
      window_handle_ = nullptr;
      Destroy();
      if (quit_on_close_) {
        PostQuitMessage(0);
      }
      return 0;

    case WM_DPICHANGED: {
      auto newRectSize = reinterpret_cast<RECT*>(lparam);
      LONG newWidth = newRectSize->right - newRectSize->left;
      LONG newHeight = newRectSize->bottom - newRectSize->top;

      SetWindowPos(hwnd, nullptr, newRectSize->left, newRectSize->top, newWidth,
                   newHeight, SWP_NOZORDER | SWP_NOACTIVATE);

      return 0;
    }
    case WM_SIZE: {
      RECT rect = GetClientArea();
      if (child_content_ != nullptr) {
        // Size and position the child window.
        MoveWindow(child_content_, rect.left, rect.top, rect.right - rect.left,
                   rect.bottom - rect.top, TRUE);
      }
      return 0;
    }

    case WM_ACTIVATE:
      if (child_content_ != nullptr) {
        SetFocus(child_content_);
      }
      return 0;

    case WM_DWMCOLORIZATIONCOLORCHANGED:
      UpdateTheme(hwnd);
      return 0;
  }

  return DefWindowProc(window_handle_, message, wparam, lparam);
}

void Win32Window::Destroy() {
  OnDestroy();

  if (window_handle_) {
    DestroyWindow(window_handle_);
    window_handle_ = nullptr;
  }
  if (g_active_window_count == 0) {
    WindowClassRegistrar::GetInstance()->UnregisterWindowClass();
  }
}

Win32Window* Win32Window::GetThisFromHandle(HWND const window) noexcept {
  return reinterpret_cast<Win32Window*>(
      GetWindowLongPtr(window, GWLP_USERDATA));
}

void Win32Window::SetChildContent(HWND content) {
  child_content_ = content;
  SetParent(content, window_handle_);
  RECT frame = GetClientArea();

  MoveWindow(content, frame.left, frame.top, frame.right - frame.left,
             frame.bottom - frame.top, true);

  SetFocus(child_content_);
}

RECT Win32Window::GetClientArea() {
  RECT frame;
  GetClientRect(window_handle_, &frame);
  return frame;
}

HWND Win32Window::GetHandle() {
  return window_handle_;
}

void Win32Window::SetQuitOnClose(bool quit_on_close) {
  quit_on_close_ = quit_on_close;
}

void Win32Window::SetFrameDarkMode(bool enabled) {
  frame_dark_mode_ = enabled;
  UpdateTheme(window_handle_);
}

bool Win32Window::OnCreate() {
  // No-op; provided for subclasses.
  return true;
}

void Win32Window::OnDestroy() {
  // No-op; provided for subclasses.
}

void Win32Window::UpdateTheme(HWND const window) {
  if (window == nullptr) {
    return;
  }
  BOOL enable_dark_mode = FALSE;
  if (frame_dark_mode_.has_value()) {
    enable_dark_mode = frame_dark_mode_.value() ? TRUE : FALSE;
  } else {
    DWORD light_mode = 1;
    DWORD light_mode_size = sizeof(light_mode);
    if (RegGetValue(HKEY_CURRENT_USER, kGetPreferredBrightnessRegKey,
                    kGetPreferredBrightnessRegValue, RRF_RT_REG_DWORD,
                    nullptr, &light_mode, &light_mode_size) == ERROR_SUCCESS) {
      enable_dark_mode = light_mode == 0 ? TRUE : FALSE;
    }
  }
  HRESULT applied = DwmSetWindowAttribute(
      window, DWMWA_USE_IMMERSIVE_DARK_MODE, &enable_dark_mode,
      sizeof(enable_dark_mode));
  if (FAILED(applied)) {
    // Windows 10 1809 used 19 before the attribute settled on 20. If neither
    // exists, leave the OS frame unchanged; content still uses the app theme.
    constexpr DWORD kLegacyImmersiveDarkMode = 19;
    applied = DwmSetWindowAttribute(window, kLegacyImmersiveDarkMode,
                                    &enable_dark_mode,
                                    sizeof(enable_dark_mode));
  }
  if (SUCCEEDED(applied)) {
    RedrawWindow(window, nullptr, nullptr, RDW_INVALIDATE | RDW_FRAME);
  }
}
