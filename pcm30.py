from enum import Enum
from bitstring import BitArray
import logging

# Enum para representar os estados da máquina de estados
class State(Enum):
    ALIGNED = 1
    REALIGNING = 2
    REALIGNMENT_CHECK = 3
    LOSS_ALIGNMENT_CHECK = 4

# Enum para representar os Sinais de alinhamento
class Signal(Enum):
    FAS  = 0x9B          #10011011 --> PAQ        (Frame Alignment Signal)
    NFAS = 0xD4          #11010100 --> b1 = 1     (Not Frame Alignment Signal) TODO - reformular essa parte

class Framing():
    """Classe que representa o procedimento para alinhamento de quadro no PCM30
    """
    def __init__(self, logging_level=logging.INFO):
        self.buffer_octeto = BitArray()   # Buffer utilizado somente no Estado Realinhando
        self.buffer_frame = BitArray()
        self.buffer_copy = BitArray()
        self.n = 1                        # número de quadros para avançar (inicia em 1)

        # Configurando Logs
        self.logger = logging.getLogger("Framming")
        logging.basicConfig(level=logging_level)

        # Definindo estado inicial
        self.logger.info("Iniciando...")
        self.state = State.REALIGNING
        self._print_state()
        self.logger.info("Procurando FAS...")
    
    # Método chamado pela função principal
    def handle_fsm(self, received_bit: bin):
        """Método para chamar a Máquina de estados passando os bits recebidos externamente
            ou bits presentes no buffer.

        Args:
            received_bit (bin): bit 0 <'0b0'> ou 1 <'0b1'>
        """
        self._fsm(received_bit)
        # Após retornar da FSM só volta a ler o arquivo se o buffer tiver vazio                         
        while len(self.buffer_copy) > 0:                # Enquanto tiver bits no buffer
            buffer_bit = self.buffer_copy.bin[0]
            del self.buffer_copy[0:1:1]
            self._fsm(self.char_to_bit(buffer_bit))

    def _fsm(self, buffer_bit):
        """Método privado que representa a máquina de estados

        Args:
            received_bit : bit recebido
        """
        # Estado REALINHANDO
        if self.state is State.REALIGNING:
            len_octeto = len(self.buffer_octeto)
            if len_octeto < 8:
                self.buffer_octeto.append(buffer_bit)
            else:
                # Deslizar octeto 
                del self.buffer_octeto[0:1:1]               # Remove bit da primeira posição
                self.buffer_octeto.append(buffer_bit)       # Insere novo bit na última

            self.logger.debug("Octeto: %s" % self.buffer_octeto.bin)
            if self.buffer_octeto.uint is Signal.FAS.value: # Verifica se temos um possível PAQ
                self.logger.info("FAS confirmado, possível PAQ encontrado!")
                self.state = State.REALIGNMENT_CHECK        # Transição de Estado
                self._print_state()

        # Estado de confirmação de Realinhamento
        elif self.state is State.REALIGNMENT_CHECK:
            frame, octeto = self._go_to_frame(self.n, buffer_bit)
            if frame == 1:   # Avançou 1 quadro     
                b1_pos = 1
                b1 = octeto.bin[b1_pos]  # Recuperando b1 para comparação
                self.logger.info("b1 (nfas) = %s" % b1)
                self.logger.debug("Buffer = %s" % self.buffer_frame.bin)

                if str(b1) == '1':                # comparação do b1
                    self.logger.info("NFAS confirmado!")
                    self.logger.debug("Buffer = %s" % self.buffer_frame.bin)
                    self.n = 2      # avançar para próximo quadro
                else:
                    self.logger.info("NFAS não confirmado, PAQ Inválido!")
                    self.state = State.REALIGNING       # Transição de Estado
                    self.buffer_copy.clear()
                    self.buffer_copy = self.buffer_frame.copy()
                    self.logger.debug("Buffer Copy= %s" % self.buffer_copy.bin)
                    self.buffer_frame.clear()
                    self.n = 1
                    self._print_state()
                    self.logger.info("Procurando FAS...")
            elif frame == 2:    # Avançou 2 quadros
                self.n = 1    # retornando n global para primeiro quadro
                if octeto.uint is Signal.FAS.value:    # Comparação do FAS
                    self.logger.info("FAS confirmado, PAQ Encontrado!")
                    self.logger.debug("Buffer = %s" % self.buffer_frame.bin)

                    self.state = State.ALIGNED       # Transição de Estado
                    self._print_state()
                    self._get_information()
                    #limpando buffers
                    self.buffer_copy.clear()
                    self.buffer_frame.clear()
                else:
                    self.logger.info("FAS não confirmado, PAQ Inválido!")
                    self.state = State.REALIGNING       # Transição de Estado
                    self.buffer_copy.clear()
                    self.buffer_copy = self.buffer_frame.copy()
                    self.logger.debug("Buffer Copy= %s" % self.buffer_copy.bin)
                    self.buffer_frame.clear()
                    self._print_state()
                    self.logger.info("Procurando FAS...")
        
        # Estado de Alinhamento
        elif self.state is State.ALIGNED:
            frame, octeto = self._go_to_frame(2, buffer_bit)  # Avançar 2 quadros
            if frame == 2:      # Avançou 2 quadros
                if octeto.uint is Signal.FAS.value:    # Comparação do FAS
                    self.logger.info("FAS confirmado, PAQ Encontrado!")
                    self._get_information()

                    self.state = State.ALIGNED       # Transição de Estado
                    self.buffer_copy.clear()
                    self.buffer_frame.clear()
                else:
                    self.logger.info("FAS não confirmado, PAQ Inválido!")
                    self.state = State.LOSS_ALIGNMENT_CHECK       # Transição de Estado
                    self._print_state()
                    self.logger.info("Verificando perda do Alinhamento...")
                    self.logger.info("Procurando FAS...")
                    self.n = 4
        
        # Estado de confirmação de perda do Alinhamento
        elif self.state is State.LOSS_ALIGNMENT_CHECK:
            frame, octeto = self._go_to_frame(self.n, buffer_bit)  # Avançar 2 quadros
            if octeto:      # Avançou quadros
                if octeto.uint is Signal.FAS.value:    # Comparação do FAS
                    self.logger.info("FAS confirmado, PAQ Encontrado!")
                    self.logger.info("Alinhamento recuperado!")
                    

                    self.state = State.ALIGNED       # Transição de Estado
                    self._print_state()
                    self._get_information()
                    self.n = 1
                    # limpando buffers
                    self.buffer_copy.clear()
                    self.buffer_frame.clear()
                else:
                    if frame == 4:       # Avançou 4 quadros
                        self.logger.info("FAS não confirmado, PAQ Inválido!")
                        self.state = State.LOSS_ALIGNMENT_CHECK       # Transição de Estado
                        self.logger.info("Procurando FAS...")
                        self.n = 6
                    
                    elif frame == 6:      # Avançou 6 quadros
                        self.logger.info("FAS não confirmado, PAQ Inválido!")
                        self.logger.info("Perda do alinhamento confirmada!")

                        self.state = State.REALIGNING       # Transição de Estado
                        self.buffer_copy.clear()
                        self.buffer_frame.clear()
                        self._print_state()
                        self.logger.info("Procurando FAS...")
                        self.n = 1
    
    @staticmethod
    def char_to_bit(char_bit: str) -> bin:
        """Função para converter um caractere em um bit

        Args:
            char_bit (str): caractere recebido para conversão

        Returns:
            bin: bit convertido
        """
        if str(char_bit) == "0":
            return '0b0'
        elif str(char_bit) == "1":
            return '0b1'
        else:
            print("Error char = %s" % char_bit)
    
    def _go_to_frame(self, n_frame: int, buffer_bit: bin) -> [int,BitArray]:
        """Método privado responsável por avançar quadros

        Args:
            n_frame (int): número de quadros para avançar
            buffer_bit (bin): bit para adicionar ao buffer

        Returns:
            int,BitArray: int --> número de quadros avançados
                          BitArray --> octeto com NFAS ou FAS para comparação
        """
        self.buffer_frame.append(buffer_bit)                        # Avançar bits até completar quadro
        len_frame = len(self.buffer_frame)
        if len_frame == (n_frame * 256):                            # Avançou n quadros
            
            if n_frame > 1:
                self.logger.info("Avançando 2 Quadros...")
            else:
                self.logger.info("Avançando 1 Quadro...")

            start_pos = len_frame - 8   # (256 - 8)
            nfas_or_fas = self.buffer_frame[start_pos:] # recuperando NFAS ou FAS
            if n_frame == 1:
                self.logger.info("NFAS = %s" % nfas_or_fas.bin)
            else:
                self.logger.info("FAS = %s" % nfas_or_fas.bin)
            
            self.logger.debug("Buffer = %s" % self.buffer_frame.bin)

            return n_frame,nfas_or_fas
        return 0, None
    
    def _get_information(self):
        """Método privado responsável por imprimir na tela o conteúdo entre PAQs
        """
        self.logger.info("Recuperando Informação...")

        end_pos_info = len(self.buffer_frame) - 8  #(512 - 8)
        information = self.buffer_frame[:end_pos_info].bin   # remover informação sem PAQ

        text = "Informação entre PAQs\n"
        text += "----------------------------------------\n"
        text += "%s\n----------------------------------------" % information

        self.logger.info(text)
                    
        self.logger.debug("Buffer = %s" % self.buffer_frame.bin)
    
    def _print_state(self):
        """Método para imprimir os estados atuais durante a execução da Máquina
        """
        self.logger.info("========================================")
        self.logger.info("Estado = %s" % self.state.name)
        self.logger.info("========================================")



def main():
    """Função principal

        Efetua a leitura do arquivo "data.txt" que contém os bits dos frames para alinhamento.
        A leitura é feita caractere por caractere que são convertidos para o formato de bit e enviado 
        para máquina de estados.
    """
    framing = Framing(logging.INFO)                    # Cria um objeto da classe Framing, responsável pelo alinhamento
    frames = open('data.txt', 'r', newline="")         # Abre o arquivo para leitura
    while True:
        char_read = frames.read(1)
        if not char_read:                              # Encerra loop se não tiver mais dados no arquivo
            break
        if (char_read == '1') or (char_read == '0'):
            bit_read = Framing.char_to_bit(char_read)  # converte caractere lido para bit 1 ou 0
            framing.handle_fsm(bit_read)               # Envia cada bit para máquina de estados

if __name__ == '__main__':
    main()