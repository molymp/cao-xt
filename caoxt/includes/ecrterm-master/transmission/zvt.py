"""
    
    Transmission Object for ZVT Protocol.
    
    @author g4b
"""
from ecrterm.transmission.signals import *
from ecrterm.transmission._transmission import Transmission, TransmissionException
from ecrterm.packets.base_packets import PacketReceived, PacketReceivedError

class ZVTTransmission(Transmission):
    """
        A Transmission Object represents an open connection between ECR and PT.
        It regulates the flow of packets, and uses a Transport
        to send its data. 
        The default Transport to use is the serial transport.
    """
    actual_timeout = TIMEOUT_T4_DEFAULT

    def __init__(self, transport):
        self.transport = transport
        self.is_master = True
        self.is_waiting = False
        self.log_list = []
        self.history = []

    def log_response(self, response):
        """
            every response is saved into self.log_list.
            hook this for live data.
        """
        self.log_list += [response]

    def send_received(self):
        """
            send the "Packet Received" Packet.
        """
        packet = PacketReceived()
        self.history += [(False, packet), ]
        self.transport.send(packet, no_wait=True)

    def handle_packet_response(self, packet, response):
        """
            a shortcut for calling the handle_response of the packet.
        """
        return packet.handle_response(response, self)

    def transmit(self, packet):
        """
            Transmit the packet, go into slave mode and wait until the
            whole sequence is finished.
        """
        if not self.is_master or self.is_waiting:
            raise TransmissionException, "Can't send until transmisson is ready"
        self.is_master = False
        try:
            self.history += [(False, packet), ]
            success, response = self.transport.send(packet)
            self.history += [(True, response), ]
            # we sent the packet.
            # now lets wait until we get master back.
            while not self.is_master:
                self.is_master = self.handle_packet_response(packet, response)
                if not self.is_master:
                    try:
                        success, response = self.transport.receive(self.actual_timeout)
                        self.history += [(True, response)]
                    except common.TransportLayerException:
                        # some kind of timeout.
                        # if we are already master, we can bravely ignore this.
                        if self.is_master:
                            return TRANSMIT_OK
                        else:
                            raise
                            return TRANSMIT_TIMEOUT
                    if self.is_master and success:
                        # we actually have to handle a last packet
                        stay_master = self.handle_packet_response(packet, response)
                        print "Is Master Read Ahead happened."
                        self.is_master = stay_master
        except Exception, e:
            print e
            self.is_master = True
            return TRANSMIT_ERROR
        self.is_master = True
        return TRANSMIT_OK
