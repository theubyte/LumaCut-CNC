// USB CDC on libopencm3. Everything USB runs in the USB_LP interrupt at low
// priority; the main loop only touches the TX ring and pends that interrupt.
#include "../../version.h"
#include "../cmd.h"
#include "../hal.h"
#include "../rxlines.h"
#include "board.h"
#include <libopencm3/cm3/nvic.h>
#include <libopencm3/usb/cdc.h>
#include <libopencm3/usb/usbd.h>
#include <string.h>

#define EP_OUT 0x01
#define EP_IN 0x82
#define EP_NOTIFY 0x83
#define PACKET 64u
#define TX_SIZE 2048u
#define TX_STALL_MS 20u

static const struct usb_device_descriptor dev_desc = {
    .bLength = USB_DT_DEVICE_SIZE,
    .bDescriptorType = USB_DT_DEVICE,
    .bcdUSB = 0x0200,
    .bDeviceClass = USB_CLASS_CDC,
    .bMaxPacketSize0 = 64,
    .idVendor = 0x0483,  // STMicroelectronics virtual COM port
    .idProduct = 0x5740,
    .bcdDevice = 0x0100,
    .iManufacturer = 1,
    .iProduct = 2,
    .iSerialNumber = 3,
    .bNumConfigurations = 1,
};

static const struct usb_endpoint_descriptor notify_ep[] = {{
    .bLength = USB_DT_ENDPOINT_SIZE,
    .bDescriptorType = USB_DT_ENDPOINT,
    .bEndpointAddress = EP_NOTIFY,
    .bmAttributes = USB_ENDPOINT_ATTR_INTERRUPT,
    .wMaxPacketSize = 16,
    .bInterval = 255,
}};

static const struct usb_endpoint_descriptor data_eps[] = {
    {
        .bLength = USB_DT_ENDPOINT_SIZE,
        .bDescriptorType = USB_DT_ENDPOINT,
        .bEndpointAddress = EP_OUT,
        .bmAttributes = USB_ENDPOINT_ATTR_BULK,
        .wMaxPacketSize = PACKET,
        .bInterval = 1,
    },
    {
        .bLength = USB_DT_ENDPOINT_SIZE,
        .bDescriptorType = USB_DT_ENDPOINT,
        .bEndpointAddress = EP_IN,
        .bmAttributes = USB_ENDPOINT_ATTR_BULK,
        .wMaxPacketSize = PACKET,
        .bInterval = 1,
    },
};

static const struct {
    struct usb_cdc_header_descriptor header;
    struct usb_cdc_call_management_descriptor call_mgmt;
    struct usb_cdc_acm_descriptor acm;
    struct usb_cdc_union_descriptor cdc_union;
} __attribute__((packed)) cdc_functional = {
    .header = {
        .bFunctionLength = sizeof(struct usb_cdc_header_descriptor),
        .bDescriptorType = CS_INTERFACE,
        .bDescriptorSubtype = USB_CDC_TYPE_HEADER,
        .bcdCDC = 0x0110,
    },
    .call_mgmt = {
        .bFunctionLength = sizeof(struct usb_cdc_call_management_descriptor),
        .bDescriptorType = CS_INTERFACE,
        .bDescriptorSubtype = USB_CDC_TYPE_CALL_MANAGEMENT,
        .bmCapabilities = 0,
        .bDataInterface = 1,
    },
    .acm = {
        .bFunctionLength = sizeof(struct usb_cdc_acm_descriptor),
        .bDescriptorType = CS_INTERFACE,
        .bDescriptorSubtype = USB_CDC_TYPE_ACM,
        .bmCapabilities = 0,
    },
    .cdc_union = {
        .bFunctionLength = sizeof(struct usb_cdc_union_descriptor),
        .bDescriptorType = CS_INTERFACE,
        .bDescriptorSubtype = USB_CDC_TYPE_UNION,
        .bControlInterface = 0,
        .bSubordinateInterface0 = 1,
    },
};

static const struct usb_interface_descriptor comm_if[] = {{
    .bLength = USB_DT_INTERFACE_SIZE,
    .bDescriptorType = USB_DT_INTERFACE,
    .bInterfaceNumber = 0,
    .bNumEndpoints = 1,
    .bInterfaceClass = USB_CLASS_CDC,
    .bInterfaceSubClass = USB_CDC_SUBCLASS_ACM,
    .bInterfaceProtocol = USB_CDC_PROTOCOL_NONE,
    .endpoint = notify_ep,
    .extra = &cdc_functional,
    .extralen = sizeof cdc_functional,
}};

static const struct usb_interface_descriptor data_if[] = {{
    .bLength = USB_DT_INTERFACE_SIZE,
    .bDescriptorType = USB_DT_INTERFACE,
    .bInterfaceNumber = 1,
    .bNumEndpoints = 2,
    .bInterfaceClass = USB_CLASS_DATA,
    .endpoint = data_eps,
}};

static const struct usb_interface ifaces[] = {
    {.num_altsetting = 1, .altsetting = comm_if},
    {.num_altsetting = 1, .altsetting = data_if},
};

static const struct usb_config_descriptor config = {
    .bLength = USB_DT_CONFIGURATION_SIZE,
    .bDescriptorType = USB_DT_CONFIGURATION,
    .wTotalLength = 0,
    .bNumInterfaces = 2,
    .bConfigurationValue = 1,
    .bmAttributes = 0x80,
    .bMaxPower = 50,
    .interface = ifaces,
};

static const char *const strings[] = {"LumaCut", LUMACUT_ID, "SKR-MINI-MZ"};

static usbd_device *dev;
static uint8_t control_buf[128];
static struct usb_cdc_line_coding line_coding = {115200, 0, 0, 8};

static volatile bool configured, dtr, suspended;
static volatile bool rx_nak;

static char tx_ring[TX_SIZE];
static volatile uint32_t tx_wr, tx_rd;
static volatile bool tx_in_flight;
static bool tx_needs_zlp;
static bool tx_stalled;

static void link_lost(void) { cmd_rt_link_lost(); }

static void tx_pump(void)
{
    if (!configured || tx_in_flight) return;
    uint8_t pkt[PACKET];
    uint32_t n = 0;
    uint32_t rd = tx_rd, wr = tx_wr;
    while (n < PACKET && rd != wr) {
        pkt[n++] = (uint8_t)tx_ring[rd % TX_SIZE];
        rd++;
    }
    if (n == 0 && !tx_needs_zlp) return;
    if (usbd_ep_write_packet(dev, EP_IN, pkt, (uint16_t)n) == 0 && n != 0) return;
    tx_rd = rd;
    tx_in_flight = true;
    tx_needs_zlp = n == PACKET; // a full packet needs an end marker if nothing follows
}

static void on_tx_done(usbd_device *d, uint8_t ep)
{
    (void)d;
    (void)ep;
    tx_in_flight = false;
    tx_pump();
}

static void on_rx(usbd_device *d, uint8_t ep)
{
    (void)ep;
    uint8_t pkt[PACKET];
    uint16_t n = usbd_ep_read_packet(d, EP_OUT, pkt, PACKET);
    if (n) rx_feed(pkt, n);
    if (!rx_can_take_packet()) {
        rx_nak = true;
        usbd_ep_nak_set(d, EP_OUT, 1);
    }
}

static enum usbd_request_return_codes on_control(usbd_device *d, struct usb_setup_data *req,
                                                 uint8_t **buf, uint16_t *len,
                                                 usbd_control_complete_callback *complete)
{
    (void)d;
    (void)complete;
    switch (req->bRequest) {
    case USB_CDC_REQ_SET_CONTROL_LINE_STATE: {
        bool now = (req->wValue & 1u) != 0;
        if (dtr && !now) link_lost();
        dtr = now;
        return USBD_REQ_HANDLED;
    }
    case USB_CDC_REQ_SET_LINE_CODING:
        if (*len < sizeof(struct usb_cdc_line_coding)) return USBD_REQ_NOTSUPP;
        memcpy(&line_coding, *buf, sizeof line_coding);
        return USBD_REQ_HANDLED;
    case USB_CDC_REQ_GET_LINE_CODING:
        *buf = (uint8_t *)&line_coding;
        *len = sizeof line_coding;
        return USBD_REQ_HANDLED;
    default:
        return USBD_REQ_NOTSUPP;
    }
}

static void on_set_config(usbd_device *d, uint16_t value)
{
    (void)value;
    usbd_ep_setup(d, EP_OUT, USB_ENDPOINT_ATTR_BULK, PACKET, on_rx);
    usbd_ep_setup(d, EP_IN, USB_ENDPOINT_ATTR_BULK, PACKET, on_tx_done);
    usbd_ep_setup(d, EP_NOTIFY, USB_ENDPOINT_ATTR_INTERRUPT, 16, NULL);
    usbd_register_control_callback(d, USB_REQ_TYPE_CLASS | USB_REQ_TYPE_INTERFACE,
                                   USB_REQ_TYPE_TYPE | USB_REQ_TYPE_RECIPIENT, on_control);
    tx_in_flight = false;
    tx_needs_zlp = false;
    rx_nak = false;
    configured = true;
}

static void on_reset(void)
{
    configured = false;
    dtr = false;
    suspended = false;
    tx_in_flight = false;
    link_lost();
}

static void on_suspend(void)
{
    suspended = true;
    link_lost();
}

static void on_resume(void) { suspended = false; }

void usb_lp_can_rx0_isr(void)
{
    usbd_poll(dev);
    if (rx_nak && rx_can_take_packet()) {
        rx_nak = false;
        usbd_ep_nak_set(dev, EP_OUT, 0);
    }
    tx_pump();
}

void usb_cdc_init(void)
{
    board_usb_release();
    dev = usbd_init(&st_usbfs_v1_usb_driver, &dev_desc, &config, strings, 3, control_buf,
                    sizeof control_buf);
    usbd_register_set_config_callback(dev, on_set_config);
    usbd_register_reset_callback(dev, on_reset);
    usbd_register_suspend_callback(dev, on_suspend);
    usbd_register_resume_callback(dev, on_resume);
    nvic_set_priority(NVIC_USB_LP_CAN_RX0_IRQ, 0xC0);
    nvic_enable_irq(NVIC_USB_LP_CAN_RX0_IRQ);
}

void usb_cdc_shutdown(void)
{
    nvic_disable_irq(NVIC_USB_LP_CAN_RX0_IRQ);
    configured = false;
    RCC_APB1ENR &= ~RCC_APB1ENR_USBEN;
    board_usb_disconnect();
}

bool hal_usb_link_ok(void) { return configured && dtr && !suspended; }

bool hal_usb_tx_idle(void) { return tx_rd == tx_wr && !tx_in_flight; }

void hal_usb_rx_resume(void)
{
    if (rx_nak) nvic_generate_software_interrupt(NVIC_USB_LP_CAN_RX0_IRQ);
}

void hal_usb_write(const char *data, size_t len)
{
    if (!configured) return;
    for (size_t i = 0; i < len; i++) {
        if (tx_wr - tx_rd >= TX_SIZE) {
            if (tx_stalled) return; // nobody reads: drop instead of waiting again
            uint32_t since = hal_ms();
            nvic_generate_software_interrupt(NVIC_USB_LP_CAN_RX0_IRQ);
            while (tx_wr - tx_rd >= TX_SIZE) {
                if (hal_ms() - since > TX_STALL_MS || !configured) {
                    tx_stalled = true;
                    return;
                }
            }
        }
        tx_stalled = false;
        tx_ring[tx_wr % TX_SIZE] = data[i];
        tx_wr = tx_wr + 1;
    }
    nvic_generate_software_interrupt(NVIC_USB_LP_CAN_RX0_IRQ);
}
